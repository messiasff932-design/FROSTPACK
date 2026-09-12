import io
import re
import unicodedata

import qrcode

# Monta o "Pix Copia e Cola" (padrão EMV do Banco Central) na mão,
# sem precisar de nenhum gateway de pagamento. É um Pix ESTÁTICO:
# não confirma pagamento sozinho, só gera o código pra pessoa pagar.


def _tlv(id_: str, value: str) -> str:
    length = str(len(value)).zfill(2)
    return f"{id_}{length}{value}"


def _limpar(txt: str, max_len: int) -> str:
    txt = txt or ""
    txt = unicodedata.normalize("NFD", txt)
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")  # remove acentos
    txt = re.sub(r"[^a-zA-Z0-9 ]", "", txt)
    return txt.strip()[:max_len].upper()


def _crc16(payload: str) -> str:
    crc = 0xFFFF
    for ch in payload:
        crc ^= ord(ch) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return format(crc, "04X")


def gerar_payload_pix(chave: str, nome: str, cidade: str, valor: float, txid: str = "***") -> str:
    """
    chave  -- Chave Pix (cpf, email, telefone ou aleatória)
    nome   -- Nome do recebedor (máx 25 caracteres)
    cidade -- Cidade do recebedor (máx 15 caracteres)
    valor  -- Valor em reais, ex: 3.00
    txid   -- Identificador da cobrança (sem espaços, até 25 chars)
    """
    merchant_account_info = _tlv("00", "BR.GOV.BCB.PIX") + _tlv("01", chave)

    valor_str = f"{float(valor):.2f}"

    payload = (
        _tlv("00", "01")  # Payload Format Indicator
        + _tlv("26", merchant_account_info)  # Merchant Account Info (Pix)
        + _tlv("52", "0000")  # Merchant Category Code
        + _tlv("53", "986")  # Moeda: BRL
        + _tlv("54", valor_str)  # Valor da transação
        + _tlv("58", "BR")  # País
        + _tlv("59", _limpar(nome, 25) or "FROST SENSI")  # Nome do recebedor
        + _tlv("60", _limpar(cidade, 15) or "SAO PAULO")  # Cidade
        + _tlv("62", _tlv("05", _limpar(txid, 25) or "***"))  # Campo adicional (txid)
    )

    payload += "6304"  # Prefixo do CRC (id 63, tamanho 04)
    crc = _crc16(payload)
    return payload + crc


def gerar_qrcode_bytes(payload: str) -> bytes:
    """Gera o QR Code (PNG em bytes) a partir do payload Pix."""
    img = qrcode.make(payload, border=1)
    img = img.resize((480, 480))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
