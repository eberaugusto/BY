import socketio
import eventlet
import time
import os

sio = socketio.Server(cors_allowed_origins='*')
app = socketio.WSGIApp(sio)

# Estado global da sala
estado_jogo = {
    "jogadores": {},           # sid -> {nome, yordle, vida_atual, vida_maxima, ataque, cartas_qtd}
    "ordem_turnos": [],        # Lista de SIDs para ordem da mesa
    "turno_idx": 0,            # Índice de quem é a vez
    "turno_fim_tempo": 0,      # Timestamp de quando o turno acaba (90s)
    "acoes_restantes": 0,
    "partida_iniciada": False,
    "carta_descarte": None
}

def avancar_turno():
    """Passa o turno para o próximo jogador vivo."""
    if not estado_jogo["partida_iniciada"] or not estado_jogo["ordem_turnos"]:
        return
    
    tamanho = len(estado_jogo["ordem_turnos"])
    for _ in range(tamanho):
        estado_jogo["turno_idx"] = (estado_jogo["turno_idx"] + 1) % tamanho
        sid_atual = estado_jogo["ordem_turnos"][estado_jogo["turno_idx"]]
        if estado_jogo["jogadores"][sid_atual]["vida_atual"] > 0:
            break

    estado_jogo["turno_fim_tempo"] = time.time() + 90
    estado_jogo["acoes_restantes"] = 1
    sio.emit("estado_atualizado", estado_jogo, room='sala_principal')

def loop_tempo_turno():
    while True:
        eventlet.sleep(1)
        if estado_jogo["partida_iniciada"] and estado_jogo["ordem_turnos"]:
            if time.time() >= estado_jogo["turno_fim_tempo"]:
                avancar_turno()

eventlet.spawn(loop_tempo_turno)

@sio.event
def connect(sid, environ):
    print(f"\n[SUCESSO] >>> Jogador conectado! SID: {sid}\n")
    # Insere automaticamente o cliente na sala unificada da partida
    sio.enter_room(sid, 'sala_principal')

@sio.event
def disconnect(sid):
    print(f"\n[AVISO] <<< Jogador desconectou. SID: {sid}\n")
    if sid in estado_jogo["jogadores"]:
        del estado_jogo["jogadores"][sid]
        if sid in estado_jogo["ordem_turnos"]:
            estado_jogo["ordem_turnos"].remove(sid)
        if len(estado_jogo["jogadores"]) < 1:
            estado_jogo["partida_iniciada"] = False
        sio.emit("estado_atualizado", estado_jogo, room='sala_principal')
        sio.emit("atualizar_lobby", list(estado_jogo["jogadores"].values()), room='sala_principal')

@sio.event
def entrar_lobby(sid, data):
    # Verifica se a partida já começou
    if estado_jogo["partida_iniciada"]:
        return

    # Validação do limite de 5 jogadores
    if len(estado_jogo["jogadores"]) >= 5 and sid not in estado_jogo["jogadores"]:
        print(f"⚠️ Tentativa de entrada rejeitada (Lobby cheio): {sid}")
        sio.emit("lobby_cheio", to=sid)
        return

    estado_jogo["jogadores"][sid] = {
        "sid": sid,
        "nome": data["nome"],
        "yordle": data["yordle"],
        "vida_atual": data["hp"],
        "vida_maxima": data["hp_max"],
        "ataque": data["atq"],
        "cartas_qtd": data["cartas_qtd"]
    }
    if sid not in estado_jogo["ordem_turnos"]:
        estado_jogo["ordem_turnos"].append(sid)
    
    # Envia os dados atualizados para todos dentro da mesma sala principal
    sio.emit("atualizar_lobby", list(estado_jogo["jogadores"].values()), room='sala_principal')

@sio.event
def iniciar_partida(sid):
    if len(estado_jogo["jogadores"]) >= 1 and not estado_jogo["partida_iniciada"]:
        estado_jogo["partida_iniciada"] = True
        estado_jogo["turno_idx"] = -1
        avancar_turno()
        sio.emit("jogo_comecou", room='sala_principal')

@sio.event
def comprar_carta(sid):
    if not estado_jogo["ordem_turnos"]:
        return
    jogador_vez = estado_jogo["ordem_turnos"][estado_jogo["turno_idx"]]
    if sid != jogador_vez or estado_jogo["acoes_restantes"] <= 0:
        return

    estado_jogo["jogadores"][sid]["cartas_qtd"] += 1
    estado_jogo["acoes_restantes"] -= 1

    if estado_jogo["acoes_restantes"] <= 0:
        avancar_turno()
    else:
        sio.emit("estado_atualizado", estado_jogo, room='sala_principal')

@sio.event
def jogar_carta(sid, data):
    if not estado_jogo["ordem_turnos"]:
        return
    jogador_vez = estado_jogo["ordem_turnos"][estado_jogo["turno_idx"]]
    if sid != jogador_vez or estado_jogo["acoes_restantes"] <= 0:
        return

    carta = data.get("carta")
    alvo_sid = data.get("alvo_sid")
    
    estado_jogo["jogadores"][sid]["cartas_qtd"] -= 1
    estado_jogo["carta_descarte"] = carta

    tipo_carta = carta[2]
    valor = carta[3]

    if alvo_sid and alvo_sid in estado_jogo["jogadores"]:
        alvo = estado_jogo["jogadores"][alvo_sid]
        if tipo_carta == "Ataque":
            alvo["vida_atual"] = max(0, alvo["vida_atual"] - valor)
        elif tipo_carta == "Cura":
            alvo["vida_atual"] = min(alvo["vida_maxima"], alvo["vida_atual"] + valor)

    if tipo_carta not in ["Feitiço", "Evento"]:
        estado_jogo["acoes_restantes"] -= 1

    if estado_jogo["acoes_restantes"] <= 0:
        avancar_turno()
    else:
        sio.emit("estado_atualizado", estado_jogo, room='sala_principal')

@sio.event
def passar_vez(sid):
    if not estado_jogo["ordem_turnos"]:
        return
    jogador_vez = estado_jogo["ordem_turnos"][estado_jogo["turno_idx"]]
    if sid == jogador_vez:
        avancar_turno()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("=====================================================")
    print("Servidor da Batalha Yordle INICIADO!")
    print(f"Porta dinâmica: {port}")
    print("O servidor está escutando na nuvem.")
    print("Aguardando jogadores...")
    print("=====================================================")
    
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
