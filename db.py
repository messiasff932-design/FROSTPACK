import os
import random
import time

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
DB_KEY = "frost_db_v2"  # mesma chave que o site usa na tabela app_data

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def _com_defaults_do_bot(db: dict) -> dict:
    """Garante que os campos usados pelo bot existam no banco, sem apagar
    nada que já esteja lá (mesmo princípio de migração usado no site)."""
    if "keys" not in db:
        db["keys"] = {}
    if "discordSettings" not in db:
        db["discordSettings"] = {
            "cargoDonoId": None,       # ID do cargo que pode usar o painel do dono
            "contadorCanal": 300,      # próximo número de canal de pagamento
            "pixKeys": [],             # [{id, chave, nome, cidade}]
            "pixAtivaId": None,        # id da chave Pix usada nas cobranças
            "paineis": {},             # painelId -> {titulo, descricao, preco, banner}
            "vendasPendentes": {},     # canalId -> {buyerId, painelId, preco, criadoEm}
        }
    return db


def load_db() -> dict:
    resp = (
        supabase.table("app_data")
        .select("value")
        .eq("key", DB_KEY)
        .maybe_single()
        .execute()
    )
    data = resp.data if resp else None
    if not data or not data.get("value"):
        raise RuntimeError(
            "O banco de dados ainda não existe (nenhuma linha encontrada). "
            "Abra o site do FROST SENSI pelo menos uma vez antes de rodar o bot, "
            "para o banco ser criado."
        )
    return _com_defaults_do_bot(data["value"])


def save_db(db: dict) -> None:
    supabase.table("app_data").upsert({"key": DB_KEY, "value": db}).execute()


# ---------------- Chaves ----------------

def _rand_key() -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    s = ""
    for i in range(16):
        if i > 0 and i % 4 == 0:
            s += "-"
        s += random.choice(chars)
    return s


def adicionar_chaves(db: dict, codigos: list) -> tuple:
    """Adiciona uma lista de códigos de chave ao banco. Ignora repetidos."""
    adicionadas = 0
    repetidas = 0
    for raw in codigos:
        code = raw.strip().upper()
        if not code:
            continue
        if code in db["keys"]:
            repetidas += 1
            continue
        db["keys"][code] = {
            "code": code,
            "status": "disponivel",
            "online": False,
            "ownerUsername": None,
            "criadaEm": int(time.time() * 1000),
        }
        adicionadas += 1
    return adicionadas, repetidas


def gerar_chaves(db: dict, quantidade: int) -> list:
    """Gera N chaves novas aleatórias e já cadastra no banco."""
    geradas = []
    for _ in range(quantidade):
        code = _rand_key()
        while code in db["keys"]:
            code = _rand_key()
        db["keys"][code] = {
            "code": code,
            "status": "disponivel",
            "online": False,
            "ownerUsername": None,
            "criadaEm": int(time.time() * 1000),
        }
        geradas.append(code)
    return geradas


def pegar_chave_disponivel(db: dict):
    """Pega uma chave disponível que ainda não foi entregue por Discord."""
    for k in db["keys"].values():
        if k.get("status") == "disponivel" and not k.get("entregueDiscord"):
            return k
    return None


def marcar_chave_entregue(db: dict, code: str, discord_user_id: str) -> None:
    """Marca uma chave como entregue via Discord (sem mexer no status,
    porque ela ainda pode ser resgatada normalmente no site depois)."""
    k = db["keys"].get(code)
    if not k:
        return
    k["entregueDiscord"] = {"userId": discord_user_id, "quando": int(time.time() * 1000)}


def contar_chaves_disponiveis(db: dict) -> int:
    return sum(
        1
        for k in db["keys"].values()
        if k.get("status") == "disponivel" and not k.get("entregueDiscord")
    )


def chaves_revogadas(db: dict) -> list:
    """Lista todas as chaves com status 'revogada', mais recentes primeiro."""
    return sorted(
        (k for k in db["keys"].values() if k.get("status") == "revogada"),
        key=lambda k: k.get("criadaEm", 0),
        reverse=True,
    )


def excluir_chave(db: dict, code: str) -> bool:
    """Remove uma chave do banco definitivamente. Só chame isso depois de
    confirmar a senha do dono E uma confirmação explícita — não tem volta."""
    code = (code or "").strip().upper()
    if code in db["keys"]:
        del db["keys"][code]
        return True
    return False


def senha_de_dono_confere(db: dict, senha: str) -> bool:
    """Confere se a senha bate com o dono principal (adminCreds) ou com
    algum dono extra (owners). Usado como segunda confirmação antes de
    ações destrutivas (excluir chave), além da checagem de cargo."""
    if not senha:
        return False
    if senha == (db.get("adminCreds") or {}).get("pass"):
        return True
    for o in db.get("owners") or []:
        if senha == o.get("pass"):
            return True
    return False
