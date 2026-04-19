import requests
import os
import pytz
import time
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# ==========================================
# CONFIGURAÇÕES E TOKENS (RAILWAY)
# ==========================================
TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM")
TOKEN_SPTRANS = os.getenv("TOKEN_SPTRANS")
SAO_PAULO_TZ = pytz.timezone('America/Sao_Paulo')

# ==========================================
# FUNÇÕES DE COMUNICAÇÃO COM A SPTRANS
# ==========================================

def autenticar(session):
    """Tenta autenticar na SPTrans com até 3 tentativas em caso de timeout"""
    url = f"https://api.olhovivo.sptrans.com.br/v2.1/Login/Autenticar?token={TOKEN_SPTRANS}"
    for _ in range(3):
        try:
            r = session.post(url, timeout=25)
            if "true" in r.text.lower():
                return True
        except Exception as e:
            print(f"Erro na autenticação: {e}")
            time.sleep(1) # Espera 1 segundo antes de tentar de novo
    return False

def buscar_previsao(session):
    """Busca a previsão de chegada no Terminal Barra Funda (Lado Sul)"""
    # Código 700015949 é um dos pontos principais da Barra Funda
    codigo_parada = "700015949"
    url = f"https://api.olhovivo.sptrans.com.br/v2.1/Previsao?codigoParada={codigo_parada}"
    
    for _ in range(2):
        try:
            r = session.get(url, timeout=25)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"Erro ao buscar previsão: {e}")
            time.sleep(1)
    return None

def extrair_opcoes(data, chegada_no_ponto):
    """Filtra as linhas 179X e 9090 e calcula o tempo de espera"""
    encontrados = []
    if not data: return encontrados

    linhas = data.get("p", {}).get("l", [])

    for linha in linhas:
        letreiro = linha.get("c", "") # Ex: 179X
        destino = linha.get("lt0", "") # Ex: Jd. Fontalis
        
        # Filtro para as suas linhas específicas
        if letreiro in ["179X", "9090"]:
            for v in linha.get("vs", []):
                horario_previsto = v.get("t") # Formato HH:MM
                if not horario_previsto:
                    continue

                # Converte o horário do ônibus para objeto datetime de hoje
                h, m = map(int, horario_previsto.split(':'))
                hora_bus = chegada_no_ponto.replace(hour=h, minute=m, second=0, microsecond=0)

                # Ajuste para virada de dia (meia-noite)
                if hora_bus < chegada_no_ponto - timedelta(hours=5):
                    hora_bus += timedelta(days=1)

                # Diferença entre sua chegada e a saída do ônibus
                diff = int((hora_bus - chegada_no_ponto).total_seconds() / 60)

                # Mostra ônibus que saem a partir do momento que você chega no ponto
                # Margem de -1 min caso você chegue correndo
                if diff >= -1:
                    encontrados.append({
                        "linha": f"{letreiro} - {destino}",
                        "horario": horario_previsto,
                        "espera": diff,
                    })
    return encontrados

# ==========================================
# HANDLER DE MENSAGENS (O QUE O BOT RESPONDE)
# ==========================================

async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        session = requests.Session()
        
        if not autenticar(session):
            await update.message.reply_text("❌ A SPTrans não está respondendo. Tente novamente em instantes.")
            return

        data = buscar_previsao(session)
        if not data:
            await update.message.reply_text("❌ Erro ao conectar com o servidor da SPTrans.")
            return

        # Pega a hora atual de SP
        agora = datetime.now(SAO_PAULO_TZ)
        tempo_caminhada = 7
        chegada_no_ponto = agora + timedelta(minutes=tempo_caminhada)

        encontrados = extrair_opcoes(data, chegada_no_ponto)

        if not encontrados:
            await update.message.reply_text(
                "Nenhum ônibus 179X ou 9090 detectado no terminal agora. 😢"
            )
            return

        # Ordena pelo ônibus que sai mais cedo após sua chegada
        encontrados.sort(key=lambda x: x["espera"])
        
        melhor = encontrados[0]
        
        resposta = (
            f"🕒 *Hora Atual:* {agora.strftime('%H:%M')}\n"
            f"🚶 *Chegada no Ponto:* {chegada_no_ponto.strftime('%H:%M')} (em {tempo_caminhada} min)\n\n"
            f"🚌 *MELHOR OPÇÃO:* \n"
            f"*{melhor['linha']}*\n"
            f"⏱ Sai às {melhor['horario']} \n"
            f"⌛ Espera: {melhor['espera']} min após você chegar\n\n"
            f"📋 *Outros horários:* \n"
        )
        
        for e in encontrados[1:3]:
            resposta += f"• {e['linha']} às {e['horario']} (+{e['espera']}m)\n"

        await update.message.reply_text(resposta, parse_mode="Markdown")

    except Exception as e:
        print(f"Erro Geral: {e}")
        await update.message.reply_text("⚠️ Ocorreu um erro ao processar sua solicitação.")

# ==========================================
# INICIALIZAÇÃO
# ==========================================

def main():
    if not TOKEN_TELEGRAM or not TOKEN_SPTRANS:
        print("ERRO: Tokens não configurados!")
        return

    app = ApplicationBuilder().token(TOKEN_TELEGRAM).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))
    
    print("🚀 Bot da Barra Funda rodando...")
    app.run_polling()

if __name__ == "__main__":
    main()