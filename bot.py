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

if not TOKEN_TELEGRAM:
    raise ValueError("TOKEN_TELEGRAM não configurado no Railway")

if not TOKEN_SPTRANS:
    raise ValueError("TOKEN_SPTRANS não configurado no Railway")


# =========================
# FUNÇÕES SPTRANS
# =========================
def autenticar(session):
    r = session.post(
        f"https://api.olhovivo.sptrans.com.br/v2.1/Login/Autenticar?token={TOKEN_SPTRANS}",
        timeout=10
    )
    return "true" in r.text.lower()


def buscar_paradas_barra_funda(session):
    r = session.get(
        "https://api.olhovivo.sptrans.com.br/v2.1/Parada/Buscar?termosBusca=barra funda",
        timeout=10
    )
    r.raise_for_status()
    return r.json()


def buscar_previsao(session, parada):
    r = session.get(
        f"https://api.olhovivo.sptrans.com.br/v2.1/Previsao?codigoParada={parada}",
        timeout=10
    )
    r.raise_for_status()
    return r.json()


def extrair_opcoes(data, chegada):
    encontrados = []

    linhas = data.get("p", {}).get("l", [])

    for linha in linhas:
        nome_linha = linha.get("c", "") or ""
        destino = linha.get("lt0", "") or ""
        identificador = f"{nome_linha} {destino}".strip()

        if "179X" in identificador or "9191" in identificador:
            for v in linha.get("vs", []):
                horario = v.get("t")
                if not horario:
                    continue

                try:
                    hora_bus = datetime.strptime(horario, "%H:%M").replace(
                        year=chegada.year,
                        month=chegada.month,
                        day=chegada.day,
                        second=0,
                        microsecond=0,
                    )

                    # Ajuste pra não dar negativo quando passa da meia-noite
                    if hora_bus < chegada:
                        hora_bus += timedelta(days=1)

                    diff = int((hora_bus - chegada).total_seconds() / 60)

                    encontrados.append({
                        "linha": identificador,
                        "horario": horario,
                        "espera": diff,
                    })

                except Exception:
                    continue

    return encontrados


# =========================
# HANDLER
# =========================
async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        session = requests.Session()

        if not autenticar(session):
            await update.message.reply_text("Erro ao autenticar na SPTrans 😢")
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
                "Não encontrei 179X ou 9191 agora 😢"
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
            f"⌛ Espera: {melhor['espera']} min\n\n"
            f"📊 Outras opções:\n"
        )

        for e in encontrados[:3]:
            resposta += f"- {e['linha']} às {e['horario']} ({e['espera']} min)\n"

        await update.message.reply_text(resposta)

    except Exception as e:
        await update.message.reply_text(f"Erro interno: {str(e)}")


# =========================
# START DO BOT
# =========================
def main():
    app = ApplicationBuilder().token(TOKEN_TELEGRAM).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))

    print("Bot rodando... 🚀")
    app.run_polling()


if __name__ == "__main__":
    main()