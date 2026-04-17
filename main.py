import requests
import os
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# =========================
# TOKENS VIA RAILWAY
# =========================
TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM")
TOKEN_SPTRANS = os.getenv("TOKEN_SPTRANS")


def autenticar(session):
    r = session.post(
        f"https://api.olhovivo.sptrans.com.br/v2.1/Login/Autenticar?token={TOKEN_SPTRANS}"
    )
    return "true" in r.text.lower()


def buscar_paradas_barra_funda(session):
    r = session.get(
        "https://api.olhovivo.sptrans.com.br/v2.1/Parada/Buscar?termosBusca=barra funda"
    )
    r.raise_for_status()
    return r.json()


def buscar_previsao(session, parada):
    r = session.get(
        f"https://api.olhovivo.sptrans.com.br/v2.1/Previsao?codigoParada={parada}"
    )
    r.raise_for_status()
    return r.json()


def extrair_opcoes(data, chegada):
    encontrados = []

    try:
        linhas = data["p"]["l"]
    except Exception:
        return encontrados

    for linha in linhas:
        nome_linha = linha.get("c", "") or ""
        destino = linha.get("lt0", "") or ""
        identificador = f"{nome_linha} {destino}".strip()

        if "179X" in identificador or "9191" in identificador:
            for v in linha.get("vs", []):
                horario = v.get("t")
                if not horario:
                    continue

                hora_bus = datetime.strptime(horario, "%H:%M").replace(
                    year=chegada.year,
                    month=chegada.month,
                    day=chegada.day,
                    second=0,
                    microsecond=0,
                )

                diff = int((hora_bus - chegada).total_seconds() / 60)

                encontrados.append({
                    "linha": identificador,
                    "horario": horario,
                    "espera": diff,
                })

    return encontrados


async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        session = requests.Session()

        if not autenticar(session):
            await update.message.reply_text("Erro ao autenticar na SPTrans.")
            return

        paradas = buscar_paradas_barra_funda(session)

        if not paradas:
            await update.message.reply_text("Não encontrei paradas da Barra Funda.")
            return

        parada = paradas[0]["cp"]

        data = buscar_previsao(session, parada)

        agora = datetime.now()
        chegada = agora + timedelta(minutes=7)

        encontrados = extrair_opcoes(data, chegada)

        if not encontrados:
            await update.message.reply_text(
                "Não encontrei 179X ou 9191 nessa parada agora."
            )
            return

        encontrados.sort(key=lambda x: x["espera"])
        melhor = encontrados[0]

        resposta = (
            f"🕒 Agora: {agora.strftime('%H:%M')}\n"
            f"🚶 Chega no ponto: {chegada.strftime('%H:%M')}\n\n"
            f"🚌 Melhor opção:\n"
            f"{melhor['linha']}\n"
            f"⏱ Sai: {melhor['horario']}\n"
            f"⌛ Espera: {melhor['espera']} min"
        )

        await update.message.reply_text(resposta)

    except Exception as e:
        await update.message.reply_text(f"Erro: {str(e)}")


app = ApplicationBuilder().token(TOKEN_TELEGRAM).build()

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))

app.run_polling()