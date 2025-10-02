import os
import re
import tempfile
import shutil
import zipfile
from io import BytesIO
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, render_template, request, flash, send_file, redirect, url_for
from werkzeug.utils import secure_filename
import pdfplumber
from fpdf import FPDF
from PIL import Image
import pandas as pd

app = Flask(__name__)
app.secret_key = 'crea-rj-secret-key-2025'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB

# Criar pasta de uploads
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Configurações - TABELA DE PONTUAÇÃO CORRIGIDA
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

def allowed_file(filename):
    return '.' in filename and filename.lower().endswith('.pdf')

def clean_text(text):
    """Limpa texto removendo espaços extras e normalizando"""
    if not text:
        return ''
    text = str(text).replace('\n', ' ').strip()
    return ' '.join(text.split())

def is_empty_info(text):
    """Verifica se o texto indica informação ausente"""
    if not text or str(text).strip() == '':
        return True
    return bool(re.search(r'^(SEM|NAO|NÃO|NAO INFORMADO|SEM INFORMAÇÃO)\s*[A-Z]*\s*$', str(text).strip(), re.IGNORECASE))

def extrair_nome_completo_agente(texto_fiscal):
    """Obtém o nome completo do agente de fiscalização"""
    if not texto_fiscal:
        return ""
    
    match = re.match(r'\d+\s*-\s*([A-Za-zÀ-ÿ\s]+)', texto_fiscal)
    if match:
        return match.group(1).strip()
    return texto_fiscal

def extrair_secao(texto, titulo_secao):
    """Extrai o conteúdo de uma seção específica do PDF"""
    try:
        padrao = re.compile(
            r'{}(.*?)(?=\d{{2}}\s*-\s*[A-Z]|\Z)'.format(re.escape(titulo_secao)), 
            re.DOTALL | re.IGNORECASE
        )
        match = padrao.search(texto)
        if match:
            conteudo = match.group(1).strip()
            return None if is_empty_info(conteudo) else conteudo
    except Exception:
        pass
    
    # Tentativa alternativa se o padrão principal não funcionar
    try:
        padrao_alternativo = re.compile(
            r'{}\s*(.*?)'.format(re.escape(titulo_secao)), 
            re.DOTALL | re.IGNORECASE
        )
        match_alt = padrao_alternativo.search(texto)
        if match_alt:
            conteudo = match_alt.group(1).strip()
            # Remove possíveis cabeçalhos de outras seções
            conteudo = re.split(r'\d{2}\s*-\s*[A-Z]', conteudo)[0].strip()
            return None if is_empty_info(conteudo) else conteudo
    except Exception:
        pass
    
    return None

def extrair_campos_basicos(texto):
    campos = {}
    
    padroes = [
        ('RF', r'Número\s*:\s*([^\n]+)'),
        ('Situação', r'Situação\s*:\s*([^\n]+)'),
        ('Fiscal', r'Agente\s+de\s+Fiscalização\s*:\s*([^\n]+)'),
        ('Data', r'Data\s+Relatório\s*:\s*([^\n]+)'),
        ('Fato_Gerador', r'Fato\s+Gerador\s*:\s*([^\n]+)'),
        ('Protocolo', r'Protocolo\s*:\s*([^\n]+)')
    ]
    
    for campo, padrao in padroes:
        try:
            match = re.search(padrao, texto)
            campos[campo] = clean_text(match.group(1)) if match else ''
        except Exception:
            campos[campo] = ''
    
    # Formatar data no padrão DD/MM/AAAA
    if campos.get('Data'):
        match_data = re.search(r'(\d{2}/\d{2}/\d{4})', campos['Data'])
        if match_data:
            # Garantir formato DD/MM/AAAA
            data_str = match_data.group(1)
            try:
                data_obj = datetime.strptime(data_str, '%d/%m/%Y')
                campos['Data'] = data_obj.strftime('%d/%m/%Y')
            except ValueError:
                campos['Data'] = data_str
    
    return campos

def extrair_rf_principal(texto):
    """Extrai o RF Principal do texto"""
    if not texto:
        return ''
    
    match = re.search(r'RF Principal\s*:\s*(\d+)', texto, re.IGNORECASE)
    if match:
        return match.group(1)
    return ''

def contar_ramos_atividade_secao_04(texto):
    """CORREÇÃO: Versão que funciona - conta 'Ramo Atividade :' na seção 04"""
    if not texto or is_empty_info(texto):
        return 0
    
    # Busca específica pela seção 04 - PADRÃO QUE FUNCIONA
    padrao = r'04\s*-\s*Identificação dos Contratados, Responsáveis Técnicos e/ou Fiscalizados(.*?)(?=05\s*-\s*Documentos Solicitados|\Z)'
    match_secao = re.search(padrao, texto, re.DOTALL | re.IGNORECASE)
    
    if not match_secao:
        return 0
    
    conteudo_secao = match_secao.group(1)
    
    # Conta as ocorrências de "Ramo Atividade :" na seção - PADRÃO QUE FUNCIONA
    ocorrencias = re.findall(r'Ramo\s+Atividade\s*:', conteudo_secao, re.IGNORECASE)
    return len(ocorrencias)

def verificar_oficio(texto):
    """Verifica se contém registros de ofício no texto (retorna 1 se sim, 0 se não)"""
    if not texto or is_empty_info(texto):
        return 0
    
    padroes = [
        r'of[ií]cio',
        r'of\.',
        r'ofc',
        r'oficio',
        r'of[\s\-]?[0-9]'
    ]
    
    texto_str = str(texto).lower()
    for padrao in padroes:
        if re.search(padrao, texto_str, re.IGNORECASE):
            return 1
    return 0

def verificar_resposta_oficio(texto):
    """Verifica se contém 'Cópia ART' no texto (retorna 1 se sim, 0 se não)"""
    if not texto or is_empty_info(texto):
        return 0
    
    texto_str = str(texto).lower()
    if re.search(r'c[óo]pia\s+art', texto_str, re.IGNORECASE):
        return 1
    return 0

def extrair_numero_protocolo(texto):
    """Extrai apenas o número do protocolo do campo Fato Gerador"""
    if not texto:
        return ''
    
    match = re.search(r'(?:PROCESSO|PROTOCOLO)[/\s]*(\d+)', texto, re.IGNORECASE)
    if match:
        return match.group(1)
    return ''

def extrair_data_art(texto):
    """Extrai a data da ART da seção 06 - Documentos Recebidos, item 'Outros'"""
    if not texto or is_empty_info(texto):
        return ''
    
    # Padrão melhorado para encontrar data no formato "OUTROS - DD/MM/AAAA"
    padrao = r'OUTROS\s*[-\s]*(\d{2}/\d{2}/\d{4})'
    match = re.search(padrao, texto, re.IGNORECASE)
    
    if match:
        data_encontrada = match.group(1)
        
        # Validar se é uma data válida e garantir formato DD/MM/AAAA
        try:
            datetime.strptime(data_encontrada, '%d/%m/%Y')
            return data_encontrada
        except ValueError:
            return ''
    
    # Tentativa alternativa com padrão mais flexível
    padrao_alternativo = r'OUTROS[^\d]*(\d{2}/\d{2}/\d{4})'
    match_alt = re.search(padrao_alternativo, texto, re.IGNORECASE)
    
    if match_alt:
        data_encontrada = match_alt.group(1)
        
        # Validar se é uma data válida e garantir formato DD/MM/AAAA
        try:
            datetime.strptime(data_encontrada, '%d/%m/%Y')
            return data_encontrada
        except ValueError:
            return ''
    
    return ''

def extrair_data_relatorio_anterior(texto):
    """CORREÇÃO: Extrai a data do relatório anterior da seção 07 - Outras Informações"""
    if not texto or is_empty_info(texto):
        return ''
    
    # Padrão para encontrar data no formato DD/MM/AAAA
    padrao = r'Data\s+do\s+Relat[óo]rio\s+Anterior\s*:\s*(\d{2}/\d{2}/\d{4})'
    match = re.search(padrao, texto, re.IGNORECASE)
    
    if match:
        data_encontrada = match.group(1)
        
        # Validar se é uma data válida
        try:
            datetime.strptime(data_encontrada, '%d/%m/%Y')
            return data_encontrada
        except ValueError:
            return ''
    
    return ''

def extrair_informacoes_complementares(texto):
    """Extrai exclusivamente o texto entre parênteses da seção Informações Complementares"""
    if not texto or is_empty_info(texto):
        return ''
    
    # Busca específica pelo padrão "Informações Complementares :" seguido de texto entre parênteses
    padrao = r'Informações\s+Complementares\s*:\s*[^(]*\(([^)]+)\)'
    match = re.search(padrao, texto, re.IGNORECASE | re.DOTALL)
    
    if match:
        return clean_text(match.group(1))
    
    return ''

def encontrar_pagina_secao_fotos(pdf):
    """Encontra a página onde está a seção 08 - Fotos"""
    for page_num, page in enumerate(pdf.pages, 1):
        texto_pagina = page.extract_text() or ""
        if re.search(r'08\s*[-]?\s*Fotos', texto_pagina, re.IGNORECASE):
            return page_num
    return None

def extrair_fotos_pdf(pdf_path, temp_dir, filename):
    """Extrai fotos do PDF de forma otimizada"""
    fotos_extraidas = []
    pdf_name = os.path.splitext(filename)[0]
    fotos_dir = os.path.join(temp_dir, "fotos", pdf_name)
    os.makedirs(fotos_dir, exist_ok=True)
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pagina_inicio_fotos = encontrar_pagina_secao_fotos(pdf)
            paginas_processar = range(len(pdf.pages))
            if pagina_inicio_fotos is not None:
                paginas_processar = range(pagina_inicio_fotos - 1, len(pdf.pages))
            
            for page_num in paginas_processar:
                pagina = pdf.pages[page_num]
                
                if hasattr(pagina, 'images') and pagina.images:
                    for img in pagina.images:
                        try:
                            # Filtro para evitar logos pequenos
                            if img.get('width', 0) < 100 or img.get('height', 0) < 100:
                                continue
                                
                            if 'stream' in img:
                                img_data = img['stream'].get_data()
                                if img_data and len(img_data) > 1000:
                                    img_name = f"foto_{len(fotos_extraidas) + 1}_pag{page_num + 1}.png"
                                    img_path = os.path.join(fotos_dir, img_name)
                                                                   
                                    with open(img_path, "wb") as f:
                                        f.write(img_data)
                                    
                                    # Verificar se a imagem é válida
                                    try:
                                        with Image.open(img_path) as test_img:
                                            test_img.verify()
                                        fotos_extraidas.append(img_path)
                                    except:
                                        if os.path.exists(img_path):
                                            os.remove(img_path)
                        except Exception:
                            continue
    except Exception:
        pass
    
    return fotos_extraidas

def determinar_regularizacao(data_art, data_relatorio_anterior):
    """CORREÇÃO: Determina se houve regularização baseado nas datas"""
    if not data_art or not data_relatorio_anterior:
        return 'NÃO'
    
    try:
        # Converter strings para objetos datetime
        data_art_dt = datetime.strptime(data_art, '%d/%m/%Y')
        data_rel_ant_dt = datetime.strptime(data_relatorio_anterior, '%d/%m/%Y')
        
        # Se a data da ART for igual ou posterior à data do relatório anterior = SIM
        if data_art_dt >= data_rel_ant_dt:
            return 'SIM'
        else:
            return 'NÃO'
    except ValueError:
        # Em caso de erro no parsing das datas
        return 'NÃO'

def processar_pdf_individual(args):
    file_path, filename, temp_dir = args
    
    try:
        with pdfplumber.open(file_path) as pdf:
            texto = "\n".join(page.extract_text() or "" for page in pdf.pages)
        
        dados = extrair_campos_basicos(texto)
        dados['Nome_Arquivo'] = filename
        dados['RF_Principal'] = extrair_rf_principal(texto)
        dados['Protocolo'] = extrair_numero_protocolo(dados.get('Fato_Gerador', ''))
        
        # Extrair nome completo do agente
        if dados.get('Fiscal'):
            dados['Fiscal_Nome_Completo'] = extrair_nome_completo_agente(dados['Fiscal'])
        else:
            dados['Fiscal_Nome_Completo'] = ''
        
        # Valores padrão
        dados['Acoes'] = 0
        dados['Oficio'] = 0
        dados['Resposta_Oficio'] = 0
        dados['Regularizacao'] = 'NÃO'
        dados['Fotos_Extraidas'] = 0
        dados['Status_Fotos'] = 'NÃO'
        dados['Fotos'] = 'Nenhuma foto extraída'
        dados['Data_ART'] = ''
        dados['Data_Relatorio_Anterior'] = ''
        dados['Informacoes_Complementares'] = ''  # NOVO CAMPO
        
        # Processar seções específicas
        secoes_importantes = [
            "04 - Identificação dos Contratados, Responsáveis Técnicos e/ou Fiscalizados",
            "05 - Documentos Solicitados / Expedidos", 
            "06 - Documentos Recebidos",
            "07 - Outras Informações"
        ]
        
        for secao in secoes_importantes:
            conteudo = extrair_secao(texto, secao)
            if conteudo:
                if "04" in secao:
                    # CORREÇÃO: Usar a função que funciona
                    dados['Acoes'] = contar_ramos_atividade_secao_04(texto)
                    print(f"DEBUG - Arquivo: {filename} - Ações encontradas: {dados['Acoes']}")
                elif "05" in secao:
                    dados['Oficio'] = verificar_oficio(conteudo)
                elif "06" in secao:
                    dados['Resposta_Oficio'] = verificar_resposta_oficio(conteudo)
                    dados['Data_ART'] = extrair_data_art(conteudo)
                elif "07" in secao:
                    # CORREÇÃO: Extrair data do relatório anterior
                    dados['Data_Relatorio_Anterior'] = extrair_data_relatorio_anterior(conteudo)
                    # NOVO: Extrair informações complementares
                    dados['Informacoes_Complementares'] = extrair_informacoes_complementares(conteudo)
        
        # CORREÇÃO: Determinar regularização baseado nas datas
        dados['Regularizacao'] = determinar_regularizacao(
            dados['Data_ART'], 
            dados['Data_Relatorio_Anterior']
        )
        
        print(f"DEBUG - Regularização: {dados['Regularizacao']} (ART: {dados['Data_ART']}, Relatório Anterior: {dados['Data_Relatorio_Anterior']})")
        
        # Extrair fotos e definir status
        fotos_extraidas = extrair_fotos_pdf(file_path, temp_dir, filename)
        dados['Fotos_Extraidas'] = len(fotos_extraidas)
        
        if dados['Fotos_Extraidas'] > 0:
            dados['Status_Fotos'] = 'SIM'
            dados['Fotos'] = f"{len(fotos_extraidas)} foto(s) extraída(s)"
        else:
            dados['Status_Fotos'] = 'NÃO'
            dados['Fotos'] = "Nenhuma foto extraída"
        
        return dados
        
    except Exception as e:
        print(f"Erro ao processar {filename}: {str(e)}")
        return {
            'Nome_Arquivo': filename,
            'RF': 'ERRO',
            'Fiscal': f"Erro no processamento",
            'Fiscal_Nome_Completo': '',
            'Data': '',
            'Acoes': 0,
            'Oficio': 0,
            'Resposta_Oficio': 0,
            'Fotos_Extraidas': 0,
            'Status_Fotos': 'NÃO',
            'Fotos': 'Erro no processamento',
            'Regularizacao': 'NÃO',
            'Data_ART': '',
            'Data_Relatorio_Anterior': '',
            'Informacoes_Complementares': ''  # NOVO CAMPO
        }

def calcular_pontuacao(dados):
    """CALCULA PONTUAÇÃO BASEADA NO STATUS DAS FOTOS"""
    try:
        # USAR STATUS_FOTOS (SIM/NÃO) para definir a tabela de pontuação
        status_fotos = dados.get('Status_Fotos', 'NÃO')
        pontuacao_tabela = TABELA_PONTUACAO[status_fotos]
        
        # Calcular protocolos (1 se tem protocolo, 0 se não tem)
        tem_protocolo = 1 if dados.get('Protocolo') and str(dados['Protocolo']).strip() else 0
        
        # CÁLCULO CORRETO DA PONTUAÇÃO
        total = (
            pontuacao_tabela['RFs'] +  # Pontuação fixa por RF
            (pontuacao_tabela['Ações'] * dados.get('Acoes', 0)) +  # Ações multiplicadas
            (pontuacao_tabela['Ofícios'] * dados.get('Oficio', 0)) +  # Ofícios multiplicados
            (pontuacao_tabela['Resposta Ofícios'] * dados.get('Resposta_Oficio', 0)) +  # Resposta multiplicada
            (pontuacao_tabela['Protocolos'] * tem_protocolo) +  # Protocolos (0 ou 1)
            pontuacao_tabela['Fotos'] +  # Pontuação fixa por fotos (baseada no status)
            (pontuacao_tabela['Regularização'] if dados.get('Regularizacao') == 'SIM' else 0)  # Regularização condicional
        )
        
        return round(total, 2)
    except Exception as e:
        print(f"Erro ao calcular pontuação: {e}")
        return 0.0

def gerar_excel(dados_lista):
    try:
        # Garantir que todas as chaves existem
        for dados in dados_lista:
            dados.setdefault('Fotos_Extraidas', 0)
            dados.setdefault('Status_Fotos', 'NÃO')
            dados.setdefault('Resposta_Oficio', 0)
            dados.setdefault('Nome_Arquivo', '')
            dados.setdefault('RF_Principal', '')
            dados.setdefault('Data_ART', '')
            dados.setdefault('Data_Relatorio_Anterior', '')
            dados.setdefault('Acoes', 0)
            dados.setdefault('Oficio', 0)
            dados.setdefault('Regularizacao', 'NÃO')
            dados.setdefault('Fiscal_Nome_Completo', '')
            dados.setdefault('Informacoes_Complementares', '')  # NOVO CAMPO
        
        df = pd.DataFrame(dados_lista)
        
        # Adicionar pontuação CORRETA
        for i, dados in enumerate(dados_lista):
            df.at[i, 'Pontuacao'] = calcular_pontuacao(dados)
        
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Dados Completos', index=False)
        
        excel_buffer.seek(0)
        return excel_buffer
    except Exception as e:
        print(f"Erro ao gerar Excel: {e}")
        empty_df = pd.DataFrame([{'Erro': 'Falha na geração do arquivo'}])
        excel_buffer = BytesIO()
        empty_df.to_excel(excel_buffer, index=False)
        excel_buffer.seek(0)
        return excel_buffer

def gerar_pdf(dados_lista):
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)
        
        # CORREÇÃO: Adicionar logo centralizado no cabeçalho
        try:
            logo_path = "10.png"
            if os.path.exists(logo_path):
                # Centralizar o logo (largura da página é 210mm, logo com 110mm)
                pdf.image(logo_path, x=50, y=10, w=110)
                pdf.ln(40)  # Espaço após o logo
        except Exception as e:
            print(f"Erro ao carregar logo: {e}")
            # Continua sem o logo se houver erro
        
        # Cabeçalho
        pdf.set_font('Arial', 'B', 16)
        pdf.cell(0, 10, 'RELATÓRIO CREA-RJ - PONTUAÇÃO', 0, 1, 'C')
        
        # Informações do Agente e Supervisão
        pdf.set_font('Arial', '', 12)
        
        # Extrair nome completo do agente (do primeiro registro válido)
        agente_nome_completo = ""
        supervisao = "SBXD"  # Valor padrão
        
        for dados in dados_lista:
            if dados.get('RF') != 'ERRO':
                # Tentar usar Fiscal_Nome_Completo primeiro, depois extrair do Fiscal
                if dados.get('Fiscal_Nome_Completo'):
                    agente_nome_completo = dados['Fiscal_Nome_Completo']
                elif dados.get('Fiscal'):
                    agente_nome_completo = extrair_nome_completo_agente(dados['Fiscal'])
                break
        
        pdf.cell(0, 10, f'Agente de Fiscalização: {agente_nome_completo}', 0, 1)
        pdf.cell(0, 10, f'Supervisão: {supervisao}', 0, 1)
        
        # Calcular período
        datas_validas = []
        for dados in dados_lista:
            if dados.get('RF') != 'ERRO' and dados.get('Data'):
                try:
                    # CORREÇÃO: Garantir formato DD/MM/AAAA
                    data_str = dados['Data']
                    if data_str:
                        data_obj = datetime.strptime(data_str, '%d/%m/%Y')
                        datas_validas.append(data_obj)
                except ValueError:
                    continue
        
        if datas_validas:
            primeira_data = min(datas_validas).strftime('%d/%m/%Y')
            ultima_data = max(datas_validas).strftime('%d/%m/%Y')
            pdf.cell(0, 10, f'Período: {primeira_data} a {ultima_data}', 0, 1)
        else:
            pdf.cell(0, 10, 'Período: Não disponível', 0, 1)
        
        pdf.cell(0, 10, f'Gerado em: {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}', 0, 1)
        pdf.cell(0, 10, f'Total de arquivos: {len(dados_lista)}', 0, 1)
        pdf.ln(10)
        
        # Tabela completa - CORREÇÃO: Ajustar larguras para mostrar 13 dígitos
        pdf.set_font('Arial', 'B', 8)
        colunas = ['RF', 'RF Principal', 'Data ART', 'Data Rel Ant', 'Regularização', 'Data', 'Ações', 'Ofícios', 'Resposta', 'Protocolos', 'Fotos', 'Pontuação']
        larguras = [20, 20, 16, 20, 22, 18, 10, 13, 15, 17, 11, 16]  # CORREÇÃO: Aumentar largura de RF e RF Principal
        
        for i, coluna in enumerate(colunas):
            pdf.cell(larguras[i], 8, coluna, 1, 0, 'C')
        pdf.ln()
        
        pdf.set_font('Arial', '', 7)
        total_acoes = 0
        total_oficios = 0
        total_resposta = 0
        total_protocolos = 0
        total_fotos_sim = 0
        total_fotos_nao = 0
        total_regularizacoes = 0
        total_pontuacao = 0
        
        for dados in dados_lista:
            if dados.get('RF') == 'ERRO':
                continue
                
            pontuacao = calcular_pontuacao(dados)
            tem_protocolo = 1 if dados.get('Protocolo') and str(dados['Protocolo']).strip() else 0
            status_fotos = dados.get('Status_Fotos', 'NÃO')
            regularizacao = dados.get('Regularizacao', 'NÃO')
            
            # CORREÇÃO: Garantir formato DD/MM/AAAA para todas as datas
            data_art = dados.get('Data_ART', '')
            data_rel_ant = dados.get('Data_Relatorio_Anterior', '')
            data_relatorio = dados.get('Data', '')
            
            # CORREÇÃO ESPECÍFICA: Exibir a data exatamente como foi extraída do PDF
            # Sem conversões automáticas que possam causar erro
            data_art_display = data_art if data_art else ''
            data_rel_ant_display = data_rel_ant if data_rel_ant else ''
            data_relatorio_display = data_relatorio if data_relatorio else ''
            
            # CORREÇÃO: Mostrar RF e RF Principal completos (13 dígitos)
            rf_text = str(dados.get('RF', ''))[:15]  # Aumentado para 15 caracteres
            rf_principal_text = str(dados.get('RF_Principal', ''))[:15]  # Aumentado para 15 caracteres
            
            pdf.cell(larguras[0], 6, rf_text, 1, 0, 'C')  # CORREÇÃO: RF completo
            pdf.cell(larguras[1], 6, rf_principal_text, 1, 0, 'C')  # CORREÇÃO: RF Principal completo
            pdf.cell(larguras[2], 6, data_art_display[:10], 1, 0, 'C')  # Data ART
            pdf.cell(larguras[3], 6, data_rel_ant_display[:10], 1, 0, 'C')  # CORREÇÃO: Data Relatório Anterior (exata do PDF)
            pdf.cell(larguras[4], 6, regularizacao, 1, 0, 'C')
            pdf.cell(larguras[5], 6, data_relatorio_display[:10], 1, 0, 'C')  # Data
            pdf.cell(larguras[6], 6, str(dados.get('Acoes', 0)), 1, 0, 'C')
            pdf.cell(larguras[7], 6, str(dados.get('Oficio', 0)), 1, 0, 'C')
            pdf.cell(larguras[8], 6, str(dados.get('Resposta_Oficio', 0)), 1, 0, 'C')
            pdf.cell(larguras[9], 6, str(tem_protocolo), 1, 0, 'C')
            pdf.cell(larguras[10], 6, status_fotos, 1, 0, 'C')
            pdf.cell(larguras[11], 6, f"{pontuacao:.2f}", 1, 0, 'C')
            pdf.ln()
            
            total_acoes += dados.get('Acoes', 0)
            total_oficios += dados.get('Oficio', 0)
            total_resposta += dados.get('Resposta_Oficio', 0)
            total_protocolos += tem_protocolo
            total_regularizacoes += 1 if regularizacao == 'SIM' else 0
            
            if status_fotos == 'SIM':
                total_fotos_sim += 1
            else:
                total_fotos_nao += 1
                
            total_pontuacao += pontuacao
        
        # Rodapé com totais
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(sum(larguras[:-1]), 6, "TOTAIS", 1, 0, 'R')
        pdf.cell(larguras[11], 6, f"{total_pontuacao:.2f}", 1, 0, 'C')
        pdf.ln()
        
        # NOVA SEÇÃO: INFORMAÇÕES COMPLEMENTARES
        pdf.ln(10)
        pdf.set_font('Arial', 'B', 14)
        pdf.cell(0, 10, 'INFORMAÇÕES COMPLEMENTARES', 0, 1, 'C')
        pdf.ln(5)
        
        # Adiciona os RFs e informações complementares apenas quando existirem dados
        pdf.set_font('Arial', '', 12)
        dados_validos = [d for d in dados_lista if d.get('RF') != 'ERRO']
        
        tem_informacoes_complementares = False
        
        for dados in dados_validos:
            # RF
            if dados.get('RF') and str(dados.get('RF', '')).strip():
                # Verifica se há informações complementares para este RF
                if dados.get('Informacoes_Complementares') and str(dados.get('Informacoes_Complementares', '')).strip():
                    tem_informacoes_complementares = True
                    
                    pdf.set_font('Arial', 'B', 12)
                    pdf.cell(30, 10, 'RF:', 0, 0)
                    pdf.set_font('Arial', '', 12)
                    pdf.cell(0, 10, str(dados.get('RF', '')), 0, 1)
                    
                    # Informações Complementares (apenas o texto entre parênteses, sem os parênteses)
                    info_complementares = str(dados.get('Informacoes_Complementares', ''))
                    pdf.multi_cell(0, 8, info_complementares)
                    
                    pdf.ln(5)
        
        # Se não houver informações complementares, mantém apenas o título
        if not tem_informacoes_complementares:
            pdf.set_font('Arial', '', 12)
            pdf.cell(0, 10, 'Nenhuma informação complementar disponível.', 0, 1, 'C')
        
        # RESUMO DE PONTUAÇÃO POR STATUS DE FOTOS
        pdf.ln(10)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 10, 'RESUMO DE PONTUAÇÃO POR STATUS DE FOTOS', 0, 1, 'C')
        pdf.ln(5)
        
        # Calcular pontuação separada para SIM e NÃO
        pontuacao_sim = sum(calcular_pontuacao(d) for d in dados_lista if d.get('Status_Fotos') == 'SIM')
        pontuacao_nao = sum(calcular_pontuacao(d) for d in dados_lista if d.get('Status_Fotos') == 'NÃO')
        
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(60, 8, 'Status Fotos', 1, 0, 'C')
        pdf.cell(60, 8, 'Quantidade', 1, 0, 'C')
        pdf.cell(60, 8, 'Pontuação Total', 1, 1, 'C')
        
        pdf.set_font('Arial', '', 10)
        pdf.cell(60, 8, 'SIM', 1, 0, 'C')
        pdf.cell(60, 8, str(total_fotos_sim), 1, 0, 'C')
        pdf.cell(60, 8, f"{pontuacao_sim:.2f}", 1, 1, 'C')
        
        pdf.cell(60, 8, 'NÃO', 1, 0, 'C')
        pdf.cell(60, 8, str(total_fotos_nao), 1, 0, 'C')
        pdf.cell(60, 8, f"{pontuacao_nao:.2f}", 1, 1, 'C')
        
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(60, 8, 'TOTAL', 1, 0, 'C')
        pdf.cell(60, 8, str(len(dados_lista)), 1, 0, 'C')
        pdf.cell(60, 8, f"{total_pontuacao:.2f}", 1, 1, 'C')
        
        # RESUMO DE REGULARIZAÇÕES
        pdf.ln(10)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 10, 'RESUMO DE REGULARIZAÇÕES', 0, 1, 'C')
        pdf.ln(5)
        
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(90, 8, 'Status Regularização', 1, 0, 'C')
        pdf.cell(90, 8, 'Quantidade', 1, 1, 'C')
        
        pdf.set_font('Arial', '', 10)
        pdf.cell(90, 8, 'SIM', 1, 0, 'C')
        pdf.cell(90, 8, str(total_regularizacoes), 1, 1, 'C')
        
        pdf.cell(90, 8, 'NÃO', 1, 0, 'C')
        pdf.cell(90, 8, str(len(dados_lista) - total_regularizacoes), 1, 1, 'C')
        
        # TABELA DE PONTUAÇÃO DE REFERÊNCIA
        pdf.ln(10)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 10, 'TABELA DE PONTUAÇÃO - REFERÊNCIA', 0, 1, 'C')
        
        pdf.set_font('Arial', 'B', 9)
        pdf.cell(40, 8, 'Item', 1, 0, 'C')
        pdf.cell(25, 8, 'SIM', 1, 0, 'C')
        pdf.cell(25, 8, 'NÃO', 1, 1, 'C')
        
        pdf.set_font('Arial', '', 8)
        for item, valores in TABELA_PONTUACAO['SIM'].items():
            pdf.cell(40, 6, item, 1, 0, 'L')
            pdf.cell(25, 6, str(valores), 1, 0, 'C')
            pdf.cell(25, 6, str(TABELA_PONTUACAO['NÃO'][item]), 1, 1, 'C')
        
        # CORREÇÃO DO ERRO: Usar output() corretamente
        pdf_output = pdf.output(dest='S')  # Retorna string
        pdf_buffer = BytesIO()
        pdf_buffer.write(pdf_output)  # Escreve a string no buffer
        pdf_buffer.seek(0)
        return pdf_buffer
        
    except Exception as e:
        print(f"Erro ao gerar PDF: {e}")
        # Fallback seguro
        try:
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font('Arial', 'B', 16)
            pdf.cell(0, 10, 'Erro na geração do relatório', 0, 1, 'C')
            pdf_output = pdf.output(dest='S')
            pdf_buffer = BytesIO()
            pdf_buffer.write(pdf_output)
            pdf_buffer.seek(0)
            return pdf_buffer
        except:
            # Último fallback
            empty_buffer = BytesIO()
            return empty_buffer

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/processar', methods=['POST'])
def processar():
    try:
        if 'pdfFiles' not in request.files:
            flash('Nenhum arquivo selecionado', 'danger')
            return redirect(url_for('index'))
        
        files = request.files.getlist('pdfFiles')
        valid_files = [f for f in files if f and allowed_file(f.filename)]
        
        if not valid_files:
            flash('Nenhum arquivo PDF válido selecionado', 'danger')
            return redirect(url_for('index'))
        
        print(f"Iniciando processamento de {len(valid_files)} arquivos...")
        
        temp_dir = tempfile.mkdtemp()
        todos_dados = []
        
        try:
            # Salvar e processar arquivos
            file_paths = []
            for file in valid_files:
                filename = secure_filename(file.filename)
                temp_path = os.path.join(temp_dir, filename)
                file.save(temp_path)
                file_paths.append((temp_path, filename, temp_dir))
            
            # Processar em paralelo
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(processar_pdf_individual, args) for args in file_paths]
                
                for future in as_completed(futures):
                    try:
                        resultado = future.result(timeout=30)
                        todos_dados.append(resultado)
                    except Exception as e:
                        print(f"Erro em future: {e}")
                        todos_dados.append({
                            'Nome_Arquivo': 'Arquivo com erro',
                            'RF': 'ERRO',
                            'Fiscal': f"Timeout ou erro",
                            'Fiscal_Nome_Completo': '',
                            'Data': '',
                            'Acoes': 0,
                            'Oficio': 0,
                            'Resposta_Oficio': 0,
                            'Fotos_Extraidas': 0,
                            'Status_Fotos': 'NÃO',
                            'Fotos': 'Erro no processamento',
                            'Regularizacao': 'NÃO',
                            'Data_ART': '',
                            'Data_Relatorio_Anterior': '',
                            'Informacoes_Complementares': ''  # NOVO CAMPO
                        })
        
            dados_validos = [d for d in todos_dados if d.get('RF') != 'ERRO']
            
            if not dados_validos:
                flash('Nenhum dado válido foi extraído dos arquivos', 'danger')
                return redirect(url_for('index'))
            
            print(f"Processados {len(dados_validos)} arquivos com sucesso")
            
            # DEBUG: Mostrar estatísticas
            total_acoes = sum(d.get('Acoes', 0) for d in dados_validos)
            total_regularizacoes = sum(1 for d in dados_validos if d.get('Regularizacao') == 'SIM')
            total_informacoes_complementares = sum(1 for d in dados_validos if d.get('Informacoes_Complementares') and str(d.get('Informacoes_Complementares')).strip())
            print(f"DEBUG - Total de ações encontradas: {total_acoes}")
            print(f"DEBUG - Total de regularizações: {total_regularizacoes}")
            print(f"DEBUG - Total de informações complementares: {total_informacoes_complementares}")
            
            for d in dados_validos:
                if d.get('Acoes', 0) > 0 or d.get('Regularizacao') == 'SIM' or d.get('Informacoes_Complementares'):
                    print(f"DEBUG - {d['Nome_Arquivo']}: {d['Acoes']} ações, Regularização: {d['Regularizacao']}, Info Complementares: {d['Informacoes_Complementares'][:50] if d['Informacoes_Complementares'] else 'Nenhuma'}")
            
            # Gerar arquivos de saída
            excel_buffer = gerar_excel(todos_dados)
            pdf_buffer = gerar_pdf(dados_validos)
            
            # Salvar arquivos
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            excel_filename = f"dados_crea_rj_{timestamp}.xlsx"
            pdf_filename = f"relatorio_crea_rj_{timestamp}.pdf"
            
            excel_path = os.path.join(app.config['UPLOAD_FOLDER'], excel_filename)
            pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], pdf_filename)
            
            with open(excel_path, 'wb') as f:
                f.write(excel_buffer.getvalue())
            
            with open(pdf_path, 'wb') as f:
                f.write(pdf_buffer.getvalue())
            
            # Estatísticas CORRIGIDAS
            total_acoes = sum(d.get('Acoes', 0) for d in dados_validos)
            total_oficios = sum(d.get('Oficio', 0) for d in dados_validos)
            total_resposta = sum(d.get('Resposta_Oficio', 0) for d in dados_validos)
            total_fotos_sim = sum(1 for d in dados_validos if d.get('Status_Fotos') == 'SIM')
            total_fotos_nao = len(dados_validos) - total_fotos_sim
            total_regularizacoes = sum(1 for d in dados_validos if d.get('Regularizacao') == 'SIM')
            total_pontuacao = sum(calcular_pontuacao(d) for d in dados_validos)
            
            flash(f'Sucesso! {len(dados_validos)} de {len(valid_files)} arquivos processados.', 'success')
            
            return render_template('resultados.html',
                                dados=dados_validos[:100],
                                total_arquivos=len(dados_validos),
                                total_fotos_sim=total_fotos_sim,
                                total_fotos_nao=total_fotos_nao,
                                total_acoes=total_acoes,
                                total_oficios=total_oficios,
                                total_resposta=total_resposta,
                                total_regularizacoes=total_regularizacoes,
                                total_pontuacao=round(total_pontuacao, 2),
                                excel_filename=excel_filename,
                                pdf_filename=pdf_filename,
                                calcular_pontuacao=calcular_pontuacao)
            
        except Exception as e:
            flash(f'Erro durante o processamento: {str(e)}', 'danger')
            return redirect(url_for('index'))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            
    except Exception as e:
        flash(f'Erro geral: {str(e)}', 'danger')
        return redirect(url_for('index'))

@app.route('/download/<filename>')
def download(filename):
    try:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        else:
            flash('Arquivo não encontrado', 'danger')
            return redirect(url_for('index'))
    except Exception as e:
        flash(f'Erro ao baixar arquivo: {str(e)}', 'danger')
        return redirect(url_for('index'))

@app.errorhandler(413)
def too_large(e):
    flash('Arquivo muito grande. Tamanho máximo permitido: 500MB', 'danger')
    return redirect(url_for('index'))

# Configurações para produção
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)