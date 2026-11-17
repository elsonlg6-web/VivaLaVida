import os
import json
import time
import uuid
import asyncio
import tempfile
import unicodedata
from pathlib import Path

import gradio as gr
from google import genai
from PIL import Image

# ==========================================================
# IDENTIDADE E CONFIGURAÇÃO
# ==========================================================
CRIADOR = "Afonso Mendonça Filgueiro"
NOME_ASSISTENTE = "MundoLouco"
MODELO = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

INSTRUCOES = """
IDENTIDADE:
Tu és o MundoLouco, um assistente virtual inteligente,
criado por Afonso Mendonça Filgueiro.
Se perguntarem quem te criou, responde claramente:
Fui criado por Afonso Mendonça Filgueiro.

PERSONALIDADE:
És inteligente, curioso, educado e descontraído.
Responde de forma objectiva, clara e organizada.
És paciente ao explicar assuntos difíceis.
Admite quando não sabes e não inventes informações.

IDIOMA:
Utiliza preferencialmente português de Angola.
Podes comunicar noutras línguas quando solicitado.
Procura compreender línguas nacionais de Angola
(Kimbundu, Umbundu, Kikongo, Cokwe, Ngangela,
Kwanyama, Nhaneca, Fiote, Ngoya e variantes).
Não inventes traduções; pede esclarecimento quando necessário.

ASSISTENTE DE ESTUDO:
Ajuda em Enfermagem, Fisiopatologia, Anatomia e Fisiologia,
Biologia, Química, Matemática, Física, Psicologia,
Metodologia Científica, Cultura Geral, História, Geografia
e Informática.
Explica passo a passo, usa exemplos, cria resumos,
exercícios e testes, corrige respostas e explica os erros.
Quando solicitado, cria testes A/B/C/D e casos práticos.
Varia a posição da resposta correcta e corrige com rigor.

FOTOGRAFIAS E DOCUMENTOS:
Analisa fotografias de apontamentos, livros e exercícios.
Transcreve e explica o conteúdo sempre que possível.
Resolve exercícios apresentados em imagens.
Se a imagem estiver ilegível, pede outra fotografia.

REGRAS:
Não inventes factos, fontes ou referências.
Em assuntos de saúde, não apresentes diagnósticos como certezas.
Protege a privacidade e não forneças instruções perigosas ou ilegais.
"""

# ==========================================================
# GEMINI
# ==========================================================
cliente = genai.Client(api_key=API_KEY) if API_KEY else None

# ==========================================================
# MEMÓRIA LOCAL
# Nota: no alojamento gratuito do Render, o disco local pode
# ser apagado em reinícios/redeploys. Para memória duradoura,
# será necessário ligar uma base de dados/armazenamento externo.
# ==========================================================
PASTA_DADOS = Path(os.getenv("DATA_DIR", "./data"))
PASTA_DADOS.mkdir(parents=True, exist_ok=True)
FICHEIRO_MEMORIA = Path(os.getenv("MEMORY_FILE", str(PASTA_DADOS / "memoria.json")))

def carregar_memoria():
    try:
        if not FICHEIRO_MEMORIA.exists():
            return {"criador": CRIADOR, "informacoes": []}
        with FICHEIRO_MEMORIA.open("r", encoding="utf-8") as f:
            dados = json.load(f)
        if not isinstance(dados, dict):
            raise ValueError("Formato de memória inválido.")
        dados.setdefault("criador", CRIADOR)
        dados.setdefault("informacoes", [])
        return dados
    except Exception:
        return {"criador": CRIADOR, "informacoes": []}

def guardar_memoria(dados):
    FICHEIRO_MEMORIA.parent.mkdir(parents=True, exist_ok=True)
    temporario = FICHEIRO_MEMORIA.with_suffix(".tmp")
    with temporario.open("w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    temporario.replace(FICHEIRO_MEMORIA)

def guardar_memoria_automatica(mensagem):
    texto = (mensagem or "").strip()
    normalizado = unicodedata.normalize("NFD", texto.lower())
    normalizado = "".join(c for c in normalizado if unicodedata.category(c) != "Mn")
    indicadores = [
        "o meu objectivo e", "meu objetivo e", "gosto de",
        "prefiro", "estou a estudar", "trabalho como",
        "o meu projecto e", "meu projeto e", "sou estudante",
        "quero desenvolver"
    ]
    if not texto or not any(p in normalizado for p in indicadores):
        return False
    dados = carregar_memoria()
    informacoes = dados.setdefault("informacoes", [])
    if texto not in informacoes:
        informacoes.append(texto)
        guardar_memoria(dados)
        return True
    return False

def preparar_prompt(mensagem, history):
    dados = carregar_memoria()
    memoria = "\n".join("- " + str(x) for x in dados.get("informacoes", []))
    partes = [
        INSTRUCOES,
        "\nMEMÓRIA DO UTILIZADOR:\n" +
        (memoria if memoria else "Ainda não existem informações adicionais."),
        "\nHISTÓRICO RECENTE:"
    ]
    # Limita o histórico enviado para controlar o tamanho do pedido.
    for item in (history or [])[-12:]:
        if isinstance(item, dict):
            role = item.get("role", "user")
            content = item.get("content", "")
            if isinstance(content, str) and content.strip():
                partes.append(f"{role}: {content}")
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            if item[0]:
                partes.append(f"Utilizador: {item[0]}")
            if item[1]:
                partes.append(f"MundoLouco: {item[1]}")
    partes.append("\nNOVA MENSAGEM DO UTILIZADOR:\n" + (mensagem or ""))
    partes.append("\nResponde em português de Angola.")
    return "\n".join(partes)

# ==========================================================
# VOZ MASCULINA (opcional)
# ==========================================================
async def gerar_audio(texto, caminho):
    import edge_tts
    comunicacao = edge_tts.Communicate(
        texto,
        voice="pt-PT-DuarteNeural",
        rate="+5%"
    )
    await comunicacao.save(caminho)

def gerar_audio_seguro(texto):
    try:
        caminho = str(Path(tempfile.gettempdir()) / f"mundolouco_{uuid.uuid4().hex}.mp3")
        asyncio.run(gerar_audio(texto, caminho))
        if os.path.exists(caminho) and os.path.getsize(caminho) > 1000:
            return caminho
    except Exception as erro:
        print("Aviso: não foi possível gerar áudio:", erro)
    return None

# ==========================================================
# CONVERSA: TEXTO + FOTOGRAFIAS + VOZ
# ==========================================================
def conversar_com_voz(mensagem, history):
    texto = ""
    ficheiros = []

    if isinstance(mensagem, dict):
        texto = mensagem.get("text", "") or ""
        ficheiros = mensagem.get("files", []) or []
    elif isinstance(mensagem, str):
        texto = mensagem

    if not texto.strip() and not ficheiros:
        return "Escreve uma mensagem ou envia uma fotografia.", None

    if cliente is None:
        return (
            "O MundoLouco ainda não está ligado ao Gemini. "
            "O administrador deve configurar a variável GEMINI_API_KEY no Render.",
            None
        )

    try:
        if texto:
            texto_limpo = texto.strip()
            normalizado = texto_limpo.lower()
            if normalizado.startswith(("lembra-te que ", "guarda que ", "recorda que ")):
                informacao = texto_limpo.split(" ", 2)[-1].strip()
                if informacao:
                    dados = carregar_memoria()
                    lista = dados.setdefault("informacoes", [])
                    if informacao not in lista:
                        lista.append(informacao)
                        guardar_memoria(dados)
                    resposta_txt = "🧠 Informação guardada na memória do MundoLouco."
                    return resposta_txt, gerar_audio_seguro(resposta_txt)

            guardar_memoria_automatica(texto)

        prompt = preparar_prompt(
            texto if texto else "Analisa esta fotografia e explica o seu conteúdo.",
            history
        )
        conteudos = [prompt]

        for ficheiro in ficheiros:
            caminho = ficheiro.get("path") if isinstance(ficheiro, dict) else ficheiro
            if caminho and os.path.exists(caminho):
                with Image.open(caminho) as img:
                    conteudos.append(img.convert("RGB").copy())

        resposta_txt = None
        for tentativa in range(3):
            try:
                resposta = cliente.models.generate_content(
                    model=MODELO,
                    contents=conteudos
                )
                resposta_txt = resposta.text or "Não consegui gerar uma resposta."
                break
            except Exception as erro:
                erro_txt = str(erro)
                # Erros 429 são limites/quota: repetir não resolve.
                if "429" in erro_txt or "RESOURCE_EXHAUSTED" in erro_txt:
                    return (
                        "A quota do Gemini foi atingida (erro 429). "
                        "É necessário aguardar a reposição da quota ou verificar "
                        "os limites e a facturação da API. As tentativas automáticas "
                        "não conseguem ultrapassar esse limite.",
                        None
                    )
                if tentativa == 2:
                    if any(c in erro_txt for c in ("503", "500", "502", "504", "408")):
                        return "O Gemini está temporariamente indisponível. Tenta novamente dentro de alguns instantes.", None
                    return f"Não consegui contactar o Gemini: {erro_txt[:500]}", None
                time.sleep(2 ** tentativa)

        audio = gerar_audio_seguro(resposta_txt)
        return resposta_txt, audio

    except Exception as erro:
        return f"Erro ao processar a mensagem: {str(erro)[:500]}", None

# ==========================================================
# INTERFACE
# ==========================================================
app = gr.ChatInterface(
    fn=conversar_com_voz,
    title="🌍 MUNDOLOUCO",
    description=(
        "Assistente inteligente e professor particular, criado por "
        f"{CRIADOR}. Envia mensagens ou fotografias; também podes ouvir "
        "as respostas quando a voz estiver disponível."
    ),
    chatbot=gr.Chatbot(height=500),
    textbox=gr.MultimodalTextbox(
        placeholder="Escreve uma mensagem ou anexa uma fotografia...",
        file_count="multiple",
        file_types=["image"],
        sources=["upload", "microphone"]
    ),
    multimodal=True,
    additional_outputs=[
        gr.Audio(label="🔊 Ouvir resposta do MundoLouco", type="filepath")
    ],
)

if __name__ == "__main__":
    app.launch(
        server_name="0.0.0.0",
        server_port=int(os.getenv("PORT", "10000"))
    )
