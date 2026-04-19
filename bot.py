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
# FUNÇÕES SPTRANS
# ==========================================

def autenticar(session):
    """Autentica na API com retentativas em caso de lentidão"""
    url = f"https://api.olhovivo.sptrans.com.br/v2.1/Login/Autenticar?token={TOKEN_SPTRANS}"
    for _ in range(3):
        try:
            r = session.post(url, timeout=25)
            if "true" in r.text.lower():
                return True
        except:
            time.sleep(1)
    return False

def buscar_dados_barra_funda(session):
    """Busca paradas reais e depois a previsão nelas (Evita erro 404)"""
    try:
        # Busca paradas pelo nome para pegar IDs atualizados
        r_paradas = session.get("https://api.olhovivo.sptrans.com.br/v2.1/Parada/Buscar?termosBusca=Barra Funda", timeout=20)
        paradas = r_paradas.json()
        
        previsoes = []
        # Olhamos as 6 primeiras paradas retornadas para cobrir o terminal todo
        for p in paradas[:6]:
            cp = p.get("cp")
            r_prev = session.get(f"https://api.olhovivo.sptrans.com.br/v2.1/Previsao?codigoParada={cp}", timeout=20)
            if r_prev.status_code == 200:
                previsoes.append(r_prev.json())
        return previsoes
    except Exception as e:
        print(f"Erro na busca dinâmica: {e}")
        return []

def filtrar_onibus(lista_previsoes, hora_chegada):
    """Processa os dados brutos e extrai apenas as linhas desejadas"""
    resultados = []
    
    for data in lista_previsoes:
        linhas = data.get("p", {}).get("l", [])
        for linha in linhas:
            letreiro = linha.get("c", "")
            destino = linha.get("lt0", "")
            
            # Filtro das suas linhas (Fontalis e Bom Retiro)
            if letreiro in ["179X", "9090"]:
                for v in linha.get("vs", []):
                    horario_str = v.get("t")
                    if not horario_str: continue

                    h, m = map(int, horario_str.split(':'))
                    hora_bus = hora_chegada.replace(hour=h, minute=m, second=0, microsecond=0)

                    # Ajuste de meia-noite
                    if hora_bus < hora_chegada - timedelta(hours=5):
                        hora_bus += timedelta(days=1)

                    diff = int((hora_bus - hora_chegada).total_seconds() / 60)

                    # Só aceita se você chegar a tempo (margem de 1 min)
                    if diff >= -1:
                        resultados.append({
                            "linha": f"{letreiro} - {destino}",
                            "horario": horario_str,
                            "espera": diff
                        })
    return resultados

# ==========================================
# HANDLER DO TELEGRAM
# ==========================================

async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        session = requests.Session()
        if not autenticar(session):
            await update.message.reply_text("❌ SPTrans fora do ar. Tente de novo.")
            return

        previsoes_brutas = buscar_dados_barra_funda(session)
        
        agora = datetime.now(SAO_PAULO_TZ)
        chegada_ponto = agora + timedelta(minutes=7) # Tempo de caminhada

        onibus_validos = filtrar_onibus(previsoes_brutas, chegada_ponto)

        if not onibus_validos:
            await update.message.reply_text("Nenhum 179X ou 9090 encontrado agora. 😢")
            return

        # Remover duplicados (mesmo ônibus em paradas próximas) e ordenar
        unicos = {f"{o['linha']}-{o['horario']}": o for o in onibus_validos}.values()
        ordenados = sorted(unicos, key=lambda x: x["espera"])

        melhor = ordenados[0]
        
        msg = (
            f"🕒 *Agora:* {agora.strftime('%H:%M')}\n"
            f"🚶 *No ponto em:* {chegada_ponto.strftime('%H:%M')} (7 min)\n\n"
            f"✅ *MELHOR OPÇÃO:* \n"
            f"🚌 *{melhor['linha']}*\n"
            f"⏱ Às {melhor['horario']} ({melhor['espera']} min de espera)\n\n"
            f"📋 *Outros próximos:* \n"
        )
        
        for e in ordenados[1:4]:
            msg += f"• {e['linha']} às {e['horario']} (+{e['espera']}m)\n"

        await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception as e:
        print(f"Erro: {e}")
        await update.message.reply_text("⚠️ Erro ao processar. Tente novamente.")

# ==========================================
# MAIN
# ==========================================

def main():
    if not TOKEN_TELEGRAM or not TOKEN_SPTRANS:
        print("Erro: Verifique as variáveis no Railway!")
        return

    app = ApplicationBuilder().token(TOKEN_TELEGRAM).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))
    
    print("🚀 Bot Barra Funda Online!")
    app.run_polling()

if __name__ == "__main__":
    main()