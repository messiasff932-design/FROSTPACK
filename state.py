# Guarda o painel que cada dono está montando, entre o modal de criação
# e o clique em "Enviar painel". Fica só na memória do bot: se o bot
# reiniciar no meio da criação, é só criar o painel de novo.
rascunhos_painel = {}  # user_id (int) -> {titulo, descricao, preco, banner}


def is_dono(member, db: dict) -> bool:
    cargo_id = db["discordSettings"].get("cargoDonoId")
    if not cargo_id:
        return member.guild_permissions.administrator
    return any(role.id == int(cargo_id) for role in member.roles)
