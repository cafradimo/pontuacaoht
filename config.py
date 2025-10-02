import os

class Config:
    SECRET_KEY = 'crea-rj-secret-key-2025'
    UPLOAD_FOLDER = 'uploads'
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB - AUMENTADO
    ALLOWED_EXTENSIONS = {'pdf'}
    
    # Configurações de processamento
    TABELA_PONTUACAO = {
        'SIM': {
            'RFs': 1,
            'Regularização': 5,
            'Ações': 1,
            'Ofícios': 1,
            'Resposta Ofícios': 2,
            'Protocolos': 1,
            'Fotos': 1
        },
        'NÃO': {
            'RFs': 0.5,
            'Regularização': 2.5,
            'Ações': 0.5,
            'Ofícios': 0.5,
            'Resposta Ofícios': 1,
            'Protocolos': 0.5,
            'Fotos': 0
        }
    }
    
    # Otimizações para grandes volumes
    CHUNK_SIZE = 10  # Processar 10 PDFs por vez
    MAX_WORKERS = 4   # Número máximo de processos paralelos