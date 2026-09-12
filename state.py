import os

# Guarda o painel que cada dono está montando, entre o modal de criação
# e o clique em "Enviar painel". Fica só na memória do bot: se o bot
# reiniciar no meio da criação, é só criar o painel de novo.
rascunhos_painel = {}  # user_id (int) -> {titulo, descricao, preco, banner}

# Formas "manuais" de definir quem é dono, direto pelas Variables do
# Railway/Render — sem precisar rodar /configurar-cargo-dono:
#   DONO_ROLE_ID   = ID do cargo (ex: o cargo "Dono" do servidor)
#   DONO_USER_IDS  = IDs de usuário separados por vírgula (ex: 123,456)
# Qualquer uma das duas (ou as duas juntas) já funciona. Se nenhuma
# estiver preenchida, continua valendo o que foi salvo no banco pelo
# comando /configurar-cargo-dono (ou o administrador do servidor).
DONO_ROLE_ID_ENV = os.environ.get("DONO_ROLE_ID", "").strip()
DONO_USER_IDS_ENV = {
    uid.strip() for uid in os.environ.get("DONO_USER_IDS", "").split(",") if uid.strip()
}


def is_dono(member, db: dict) -> bool:
    if str(member.id) in DONO_USER_IDS_ENV:
        return True

    if DONO_ROLE_ID_ENV and any(str(role.id) == DONO_ROLE_ID_ENV for role in member.roles):
        return True

    cargo_id = db["discordSettings"].get("cargoDonoId")
    if not cargo_id:
        return member.guild_permissions.administrator
    return any(role.id == int(cargo_id) for role in member.roles)
