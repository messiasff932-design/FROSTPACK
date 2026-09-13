import asyncio
import io
import os
import time

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from db import (
    adicionar_chaves,
    contar_chaves_disponiveis,
    excluir_chave,
    gerar_chaves,
    load_db,
    marcar_chave_entregue,
    pegar_chave_disponivel,
    resetar_chave,
    save_db,
)
from pix import gerar_payload_pix, gerar_qrcode_bytes
from state import is_dono, rascunhos_painel

load_dotenv()

GUILD_ID = os.environ.get("GUILD_ID")
GUILD_OBJECT = discord.Object(id=int(GUILD_ID)) if GUILD_ID else None

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


# ---------------- utilitários ----------------

def preco_str(v) -> str:
    return "R$ " + f"{float(v):.2f}".replace(".", ",")


def embed_painel(titulo, descricao, preco, banner) -> discord.Embed:
    embed = discord.Embed(title=titulo, description=descricao, color=0x6FE0FF)
    embed.set_footer(text=f"Preço: {preco_str(preco)}")
    if banner:
        embed.set_image(url=banner)
    return embed


async def acesso_negado(interaction: discord.Interaction):
    await interaction.response.send_message(
        "🚫 Você não tem o cargo de dono para usar isso.", ephemeral=True
    )


async def run_db(func, *args, **kwargs):
    """Roda chamadas (síncronas) ao Supabase numa thread separada,
    pra não travar o loop de eventos do bot."""
    return await asyncio.to_thread(func, *args, **kwargs)


# ---------------- comandos de barra ----------------

@bot.tree.command(
    name="configurar-cargo-dono",
    description="Define qual cargo pode usar o painel do dono e cadastrar chaves/Pix.",
)
@app_commands.describe(cargo="Cargo que terá acesso de dono no bot")
@app_commands.default_permissions(administrator=True)
async def configurar_cargo_dono(interaction: discord.Interaction, cargo: discord.Role):
    # Avisa o Discord para esperar o banco de dados responder
    await interaction.response.defer(ephemeral=True)

    db = await run_db(load_db)
    db["discordSettings"]["cargoDonoId"] = str(cargo.id)
    await run_db(save_db, db)

    # Envia a mensagem de sucesso usando o followup
    await interaction.followup.send(
        f"✅ Cargo de dono do bot definido como {cargo.mention}."
    )


@bot.tree.command(
    name="cadastrar-chaves",
    description="Abre um formulário para colar várias chaves separadas por vírgula.",
)
async def cadastrar_chaves(interaction: discord.Interaction):
    db = await run_db(load_db)
    if not is_dono(interaction.user, db):
        return await acesso_negado(interaction)
    await interaction.response.send_modal(ModalCadastrarChaves())


@bot.tree.command(
    name="gerar-chaves",
    description="Gera chaves novas automaticamente e já cadastra no banco.",
)
@app_commands.describe(quantidade="Quantas chaves gerar")
async def gerar_chaves_cmd(
    interaction: discord.Interaction, quantidade: app_commands.Range[int, 1, 500]
):
    db = await run_db(load_db)
    if not is_dono(interaction.user, db):
        return await acesso_negado(interaction)

    await interaction.response.defer(ephemeral=True)

    geradas = gerar_chaves(db, quantidade)
    await run_db(save_db, db)

    arquivo = discord.File(
        io.BytesIO("\n".join(geradas).encode("utf-8")),
        filename=f"chaves-frost-sensi-{int(time.time() * 1000)}.txt",
    )
    await interaction.followup.send(
        content=f"✅ {len(geradas)} chaves geradas e cadastradas no banco.",
        file=arquivo,
    )


@bot.tree.command(
    name="gerenciar-chave",
    description="Reseta (deixa disponível de novo) ou exclui uma chave específica pelo código.",
)
@app_commands.describe(
    codigo="Código da chave (ex: ABCD-EFGH-...)",
    acao="O que fazer com essa chave",
)
@app_commands.choices(
    acao=[
        app_commands.Choice(name="Resetar (deixa disponível de novo)", value="resetar"),
        app_commands.Choice(name="Excluir (apaga a chave definitivamente)", value="excluir"),
    ]
)
async def gerenciar_chave(
    interaction: discord.Interaction, codigo: str, acao: app_commands.Choice[str]
):
    db = await run_db(load_db)
    if not is_dono(interaction.user, db):
        return await acesso_negado(interaction)

    await interaction.response.defer(ephemeral=True)

    code = codigo.strip().upper()
    if code not in db["keys"]:
        return await interaction.followup.send(f"⚠️ Chave `{code}` não encontrada.", ephemeral=True)

    if acao.value == "resetar":
        resetar_chave(db, code)
        await run_db(save_db, db)
        return await interaction.followup.send(
            f"🔄 Chave `{code}` resetada — ela está disponível de novo pra ser entregue.",
            ephemeral=True,
        )
    else:
        excluir_chave(db, code)
        await run_db(save_db, db)
        return await interaction.followup.send(
            f"🗑️ Chave `{code}` excluída definitivamente do banco.", ephemeral=True
        )


@bot.tree.command(
    name="painel-dono",
    description="Abre o painel de administração do bot (só para o cargo de dono).",
)
async def painel_dono(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    db = await run_db(load_db)
    if not is_dono(interaction.user, db):
        return await interaction.followup.send(
            "🚫 Você não tem o cargo de dono para usar isso.", ephemeral=True
        )

    disponiveis = contar_chaves_disponiveis(db)

    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            custom_id="pd_criar_painel", label="Criar painel", style=discord.ButtonStyle.primary
        )
    )
    view.add_item(
        discord.ui.Button(
            custom_id="pd_cadastrar_pix", label="Chave Pix", style=discord.ButtonStyle.secondary
        )
    )
    view.add_item(
        discord.ui.Button(
            custom_id="pd_ver_pix",
            label="Ver Pix cadastrados",
            style=discord.ButtonStyle.secondary,
        )
    )
    view.add_item(
        discord.ui.Button(
            custom_id="pd_remover_pix",
            label="Remover Pix",
            style=discord.ButtonStyle.danger,
        )
    )

    await interaction.followup.send(
        content=f"**Painel do dono**\nChaves disponíveis para venda: **{disponiveis}**",
        view=view,
        ephemeral=True,
    )


# ---------------- modais ----------------

class ModalCadastrarChaves(discord.ui.Modal, title="Cadastrar chaves"):
    chaves_lista = discord.ui.TextInput(
        label="Cole as chaves separadas por vírgula",
        style=discord.TextStyle.paragraph,
        placeholder="CHAVE1, CHAVE2, CHAVE3, ...",
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        db = await run_db(load_db)
        codigos = str(self.chaves_lista.value).split(",")
        adicionadas, repetidas = adicionar_chaves(db, codigos)
        await run_db(save_db, db)
        extra = f" ({repetidas} já existiam e foram ignoradas.)" if repetidas else ""
        await interaction.followup.send(
            f"✅ {adicionadas} chave(s) cadastrada(s).{extra}", ephemeral=True
        )


class ModalCriarPainel(discord.ui.Modal, title="Criar painel de vendas"):
    painel_titulo = discord.ui.TextInput(
        label="Título", style=discord.TextStyle.short, required=True
    )
    painel_desc = discord.ui.TextInput(
        label="Descrição", style=discord.TextStyle.paragraph, required=True
    )
    painel_preco = discord.ui.TextInput(
        label="Preço (ex: 3.00)", style=discord.TextStyle.short, required=True
    )
    painel_banner = discord.ui.TextInput(
        label="URL do banner (640x260, .png)", style=discord.TextStyle.short, required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        titulo = str(self.painel_titulo.value)
        descricao = str(self.painel_desc.value)
        banner = str(self.painel_banner.value)
        try:
            preco = float(str(self.painel_preco.value).replace(",", "."))
        except ValueError:
            preco = None

        if preco is None or preco <= 0:
            return await interaction.response.send_message(
                "⚠️ Preço inválido. Use algo como 3.00", ephemeral=True
            )

        rascunhos_painel[interaction.user.id] = {
            "titulo": titulo,
            "descricao": descricao,
            "preco": preco,
            "banner": banner,
        }

        view = discord.ui.View(timeout=None)
        view.add_item(
            discord.ui.Button(
                custom_id="pd_enviar_painel", label="Enviar painel", style=discord.ButtonStyle.success
            )
        )

        await interaction.response.send_message(
            content="Pré-visualização do painel:",
            embed=embed_painel(titulo, descricao, preco, banner),
            view=view,
            ephemeral=True,
        )


class ModalCadastrarPix(discord.ui.Modal, title="Cadastrar chave Pix"):
    pix_chave = discord.ui.TextInput(label="Chave Pix", style=discord.TextStyle.short, required=True)
    pix_nome = discord.ui.TextInput(
        label="Nome do recebedor", style=discord.TextStyle.short, required=True
    )
    pix_cidade = discord.ui.TextInput(
        label="Cidade do recebedor", style=discord.TextStyle.short, required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        db = await run_db(load_db)
        chave = str(self.pix_chave.value).strip()
        nome = str(self.pix_nome.value).strip()
        cidade = str(self.pix_cidade.value).strip()

        pix_id = "pix" + str(int(time.time() * 1000))
        db["discordSettings"]["pixKeys"].append(
            {"id": pix_id, "chave": chave, "nome": nome, "cidade": cidade}
        )
        db["discordSettings"]["pixAtivaId"] = pix_id
        await run_db(save_db, db)

        await interaction.followup.send(
            f"✅ Chave Pix de **{nome}** cadastrada e definida como ativa.", ephemeral=True
        )


# ---------------- botões do painel do dono ----------------

async def on_botao_ver_pix(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    db = await run_db(load_db)
    lista = db["discordSettings"]["pixKeys"]
    if not lista:
        return await interaction.followup.send(
            "Nenhuma chave Pix cadastrada ainda.", ephemeral=True
        )
    ativa_id = db["discordSettings"]["pixAtivaId"]
    linhas = [
        f"{'✅ (ativa)' if p['id'] == ativa_id else '⬜'} **{p['nome']}** — `{p['chave']}` — {p['cidade']}"
        for p in lista
    ]
    await interaction.followup.send("\n".join(linhas), ephemeral=True)


async def on_botao_remover_pix(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    db = await run_db(load_db)
    lista = db["discordSettings"]["pixKeys"]
    if not lista:
        return await interaction.followup.send(
            "Nenhuma chave Pix cadastrada ainda.", ephemeral=True
        )

    ativa_id = db["discordSettings"]["pixAtivaId"]
    options = []
    for p in lista[:25]:  # o Discord só permite até 25 opções num select
        marca = "✅ " if p["id"] == ativa_id else ""
        options.append(
            discord.SelectOption(
                label=f"{marca}{p['nome']} — {p['cidade']}"[:100],
                description=p["chave"][:100],
                value=p["id"],
            )
        )

    select = discord.ui.Select(
        custom_id="select_remover_pix",
        placeholder="Escolha qual chave Pix remover",
        options=options,
    )
    view = discord.ui.View(timeout=None)
    view.add_item(select)
    await interaction.followup.send(
        content="Selecione a chave Pix que deseja remover:", view=view, ephemeral=True
    )


async def on_select_remover_pix(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    values = (interaction.data or {}).get("values", [])
    if not values:
        return await interaction.followup.send("⚠️ Nada selecionado.", ephemeral=True)
    pix_id = values[0]

    db = await run_db(load_db)
    lista = db["discordSettings"]["pixKeys"]
    removida = next((p for p in lista if p["id"] == pix_id), None)
    if not removida:
        return await interaction.followup.send("⚠️ Essa chave já não existe mais.", ephemeral=True)

    db["discordSettings"]["pixKeys"] = [p for p in lista if p["id"] != pix_id]

    # Se a chave removida era a ativa, define outra como ativa (se sobrar
    # alguma) ou deixa None (aí "Confirmar compra" avisa pra cadastrar uma nova).
    if db["discordSettings"]["pixAtivaId"] == pix_id:
        restantes = db["discordSettings"]["pixKeys"]
        db["discordSettings"]["pixAtivaId"] = restantes[0]["id"] if restantes else None

    await run_db(save_db, db)
    await interaction.followup.send(
        f"🗑️ Chave Pix de **{removida['nome']}** removida.", ephemeral=True
    )


# ---------------- enviar painel para um canal ----------------

async def on_botao_enviar_painel(interaction: discord.Interaction):
    rascunho = rascunhos_painel.get(interaction.user.id)
    if not rascunho:
        return await interaction.response.send_message(
            "⚠️ Esse rascunho expirou, crie o painel de novo.", ephemeral=True
        )
    select = discord.ui.ChannelSelect(
        custom_id="select_canal_painel",
        placeholder="Escolha o canal para enviar o painel",
        channel_types=[discord.ChannelType.text],
    )
    view = discord.ui.View(timeout=None)
    view.add_item(select)
    await interaction.response.send_message(
        content="Em qual canal você deseja enviar esse painel?",
        view=view,
        ephemeral=True,
    )


async def on_select_canal_painel(interaction: discord.Interaction):
    rascunho = rascunhos_painel.get(interaction.user.id)
    if not rascunho:
        return await interaction.response.edit_message(
            content="⚠️ Esse rascunho expirou, crie o painel de novo.", view=None
        )

    values = (interaction.data or {}).get("values", [])
    if not values:
        return await interaction.response.edit_message(
            content="⚠️ Nenhum canal selecionado.", view=None
        )
    canal = interaction.guild.get_channel(int(values[0]))

    # Responde já (edit_message conta como a resposta), antes de mexer no banco
    await interaction.response.edit_message(content="Enviando painel...", view=None)

    db = await run_db(load_db)
    painel_id = "painel" + str(int(time.time() * 1000))
    db["discordSettings"]["paineis"][painel_id] = rascunho
    await run_db(save_db, db)

    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            custom_id=f"buy_{painel_id}", label="Comprar", style=discord.ButtonStyle.success
        )
    )
    await canal.send(embed=embed_painel(**rascunho), view=view)

    rascunhos_painel.pop(interaction.user.id, None)
    await interaction.edit_original_response(content=f"✅ Painel enviado em {canal.mention}.")


# ---------------- fluxo de compra ----------------

async def on_botao_comprar(interaction: discord.Interaction, painel_id: str):
    await interaction.response.defer(ephemeral=True)

    db = await run_db(load_db)
    painel = db["discordSettings"]["paineis"].get(painel_id)
    if not painel:
        return await interaction.followup.send(
            "⚠️ Esse painel não existe mais.", ephemeral=True
        )

    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            custom_id=f"buyyes_{painel_id}", label="Sim", style=discord.ButtonStyle.success
        )
    )
    view.add_item(
        discord.ui.Button(
            custom_id=f"buyno_{painel_id}", label="Não", style=discord.ButtonStyle.danger
        )
    )

    await interaction.followup.send(
        content=f"Você deseja comprar **{painel['titulo']}** por **{preco_str(painel['preco'])}**?",
        view=view,
        ephemeral=True,
    )


async def on_botao_comprar_nao(interaction: discord.Interaction):
    await interaction.response.edit_message(content="Compra cancelada.", view=None)


async def on_botao_comprar_sim(interaction: discord.Interaction, painel_id: str):
    await interaction.response.edit_message(content="Criando seu canal de pagamento...", view=None)

    db = await run_db(load_db)
    painel = db["discordSettings"]["paineis"].get(painel_id)
    if not painel:
        return await interaction.followup.send("⚠️ Esse painel não existe mais.", ephemeral=True)

    chave = pegar_chave_disponivel(db)
    if not chave:
        return await interaction.followup.send(
            "😕 Sem chaves disponíveis no momento. Fale com o dono.", ephemeral=True
        )

    if not db["discordSettings"]["pixAtivaId"]:
        return await interaction.followup.send(
            "⚠️ Nenhuma chave Pix cadastrada ainda. Avise o dono.", ephemeral=True
        )
    pix = next(
        p for p in db["discordSettings"]["pixKeys"] if p["id"] == db["discordSettings"]["pixAtivaId"]
    )

    numero = db["discordSettings"].get("contadorCanal", 300)
    db["discordSettings"]["contadorCanal"] = numero + 1

    guild = interaction.guild
    cargo_dono_id = db["discordSettings"].get("cargoDonoId")

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
    }
    if cargo_dono_id:
        cargo = guild.get_role(int(cargo_dono_id))
        if cargo:
            overwrites[cargo] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

    canal = await guild.create_text_channel(name=f"pagamento-{numero}", overwrites=overwrites)

    db["discordSettings"]["vendasPendentes"][str(canal.id)] = {
        "buyerId": str(interaction.user.id),
        "painelId": painel_id,
        "preco": painel["preco"],
        "criadoEm": int(time.time() * 1000),
    }
    await run_db(save_db, db)

    payload = gerar_payload_pix(
        chave=pix["chave"],
        nome=pix["nome"],
        cidade=pix["cidade"],
        valor=painel["preco"],
        txid=str(canal.id)[-20:],
    )
    qr_bytes = gerar_qrcode_bytes(payload)
    attachment = discord.File(io.BytesIO(qr_bytes), filename="pix.png")

    embed = discord.Embed(
        title=f"Pagamento — {painel['titulo']}",
        description=(
            f"Valor: **{preco_str(painel['preco'])}**\n\n"
            "Escaneie o QR Code abaixo com o app do seu banco, ou copie o código Pix."
        ),
        color=0x6FE0FF,
    )
    embed.set_image(url="attachment://pix.png")

    view_pagamento = discord.ui.View(timeout=None)
    view_pagamento.add_item(
        discord.ui.Button(
            custom_id=f"copiarpix_{canal.id}",
            label="Copiar Pix Copia e Cola",
            style=discord.ButtonStyle.secondary,
        )
    )
    view_pagamento.add_item(
        discord.ui.Button(
            custom_id=f"confirmar_{canal.id}", label="Confirmar compra", style=discord.ButtonStyle.success
        )
    )

    await canal.send(
        content=f"<@{interaction.user.id}>",
        embed=embed,
        file=attachment,
        view=view_pagamento,
    )


# ---------------- copiar pix / confirmar compra ----------------

async def on_botao_copiar_pix(interaction: discord.Interaction, canal_id: str):
    await interaction.response.defer(ephemeral=True)

    db = await run_db(load_db)
    venda = db["discordSettings"]["vendasPendentes"].get(canal_id)
    if not venda:
        return await interaction.followup.send(
            "⚠️ Essa cobrança não existe mais.", ephemeral=True
        )
    pix = next(
        p for p in db["discordSettings"]["pixKeys"] if p["id"] == db["discordSettings"]["pixAtivaId"]
    )
    payload = gerar_payload_pix(
        chave=pix["chave"],
        nome=pix["nome"],
        cidade=pix["cidade"],
        valor=venda["preco"],
        txid=canal_id[-20:],
    )
    await interaction.followup.send(f"```{payload}```", ephemeral=True)


async def on_botao_confirmar_compra(interaction: discord.Interaction, canal_id: str):
    await interaction.response.defer()

    db = await run_db(load_db)
    if not is_dono(interaction.user, db):
        return await interaction.followup.send(
            "🚫 Você não tem o cargo de dono para usar isso.", ephemeral=True
        )

    venda = db["discordSettings"]["vendasPendentes"].get(canal_id)
    if not venda:
        return await interaction.followup.send(
            "⚠️ Essa cobrança não existe mais.", ephemeral=True
        )

    chave = pegar_chave_disponivel(db)
    if not chave:
        return await interaction.followup.send(
            "😕 Sem chaves disponíveis para entregar.", ephemeral=True
        )

    marcar_chave_entregue(db, chave["code"], venda["buyerId"])
    del db["discordSettings"]["vendasPendentes"][canal_id]
    await run_db(save_db, db)

    comprador = await bot.fetch_user(int(venda["buyerId"]))
    try:
        await comprador.send(
            "✅ Pagamento confirmado! Aqui está sua chave de acesso do **FROST SENSI**:\n"
            f"```{chave['code']}```\n"
            'Use essa chave em "Criar conta" no site para liberar seu acesso.'
        )
    except discord.Forbidden:
        await interaction.channel.send(
            "⚠️ Não consegui enviar a chave no privado do comprador (DM fechada). "
            f"Envie manualmente: `{chave['code']}`"
        )

    await interaction.followup.send(
        "✅ Compra confirmada, chave enviada no privado do cliente. Este canal será apagado em 10 segundos."
    )

    canal = interaction.channel

    async def apagar_depois():
        await asyncio.sleep(10)
        try:
            await canal.delete()
        except Exception:
            pass

    bot.loop.create_task(apagar_depois())


# ---------------- roteador de interações (botões / select menus) ----------------

@bot.event
async def on_interaction(interaction: discord.Interaction):
    try:
        if interaction.type is not discord.InteractionType.component:
            return  # comandos de barra e modais já são tratados pelo tree/on_submit

        data = interaction.data or {}
        component_type = data.get("component_type")
        custom_id = data.get("custom_id", "")

        if component_type == 2:  # botão
            if custom_id == "pd_criar_painel":
                return await interaction.response.send_modal(ModalCriarPainel())
            if custom_id == "pd_cadastrar_pix":
                return await interaction.response.send_modal(ModalCadastrarPix())
            if custom_id == "pd_ver_pix":
                return await on_botao_ver_pix(interaction)
            if custom_id == "pd_remover_pix":
                return await on_botao_remover_pix(interaction)
            if custom_id == "pd_enviar_painel":
                return await on_botao_enviar_painel(interaction)
            if custom_id.startswith("buy_"):
                return await on_botao_comprar(interaction, custom_id[len("buy_"):])
            if custom_id.startswith("buyno_"):
                return await on_botao_comprar_nao(interaction)
            if custom_id.startswith("buyyes_"):
                return await on_botao_comprar_sim(interaction, custom_id[len("buyyes_"):])
            if custom_id.startswith("copiarpix_"):
                return await on_botao_copiar_pix(interaction, custom_id[len("copiarpix_"):])
            if custom_id.startswith("confirmar_"):
                return await on_botao_confirmar_compra(interaction, custom_id[len("confirmar_"):])

        elif component_type == 3 and custom_id == "select_remover_pix":  # string select
            return await on_select_remover_pix(interaction)

        elif component_type == 8 and custom_id == "select_canal_painel":  # channel select
            return await on_select_canal_painel(interaction)

    except Exception as err:
        print("Erro numa interação:", err)
        msg = "⚠️ Deu um erro aqui, olha o console do bot."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


# ---------------- tratador de erro geral pra comandos de barra ----------------
# Sem isso, se um comando (/painel-dono, /gerar-chaves, etc.) der qualquer
# erro inesperado antes de responder, o Discord só mostra "O aplicativo não
# respondeu" e não aparece nada no console. Com isso aqui, o erro some do
# silêncio: aparece no log do bot E o usuário recebe uma mensagem.

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print("Erro num comando de barra:", repr(error))
    msg = "⚠️ Deu um erro nesse comando, olha o console do bot."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass


# ---------------- inicialização ----------------

@bot.event
async def on_ready():
    try:
        if GUILD_OBJECT:
            bot.tree.copy_global_to(guild=GUILD_OBJECT)
            synced = await bot.tree.sync(guild=GUILD_OBJECT)
            print(f"✅ {len(synced)} comando(s) registrados neste servidor (aparecem na hora).")
        else:
            synced = await bot.tree.sync()
            print(
                f"✅ {len(synced)} comando(s) registrados globalmente "
                "(pode levar até 1h para aparecer)."
            )
    except Exception as err:
        print("Erro ao sincronizar comandos:", err)

    print(f"✅ Bot online como {bot.user}")


if __name__ == "__main__":
    bot.run(os.environ.get("DISCORD_TOKEN"))
