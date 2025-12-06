from flask import Flask, request, jsonify, render_template
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin, urlparse
import os
from dotenv import load_dotenv 

# =============================================================
# Configuração Inicial e Chave API
# =============================================================

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv() 

app = Flask(__name__)

# A chave da API PAGESPEED é lida do .env ou do ambiente de hospedagem
PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY") 

# =============================================================
# MÓDULO DE VERIFICAÇÃO ON-PAGE E CONTEÚDO
# =============================================================

def verificar_titulo(soup):
    title_tag = soup.find('title')
    title = title_tag.text.strip() if title_tag and title_tag.text else "NÃO ENCONTRADO"
    length = len(title)
    status = "OK"
    sugestao = "O comprimento está ideal (30-60 caracteres)."
    
    if title == "NÃO ENCONTRADO":
        status = "ERRO"
        sugestao = "Title Tag ausente."
    elif length < 30:
        status = "AVISO"
        sugestao = f"O Title Tag é muito curto ({length} caracteres). Sugerimos mais de 30."
    elif length > 60:
        status = "AVISO"
        sugestao = f"O Title Tag é muito longo ({length} caracteres). Sugerimos menos de 60."

    return {"valor": title, "comprimento": length, "status": status, "sugestao": sugestao}

def verificar_meta_description(soup):
    meta_description_tag = soup.find('meta', attrs={'name': 'description'})
    description = meta_description_tag.get('content').strip() if meta_description_tag and meta_description_tag.get('content') else "NÃO ENCONTRADA"
    
    length = len(description) if description != "NÃO ENCONTRADA" else 0
    status = "OK"
    sugestao = "O comprimento está ideal (70-160 caracteres)."
    
    if length == 0:
        status = "ERRO"
        sugestao = "Meta Description ausente. É essencial para o CTR (taxa de cliques)."
    elif length < 70:
        status = "AVISO"
        sugestao = f"A Meta Description é muito curta ({length} caracteres). Sugerimos mais de 70."
    elif length > 160:
        status = "AVISO"
        sugestao = f"A Meta Description é muito longa ({length} caracteres). Sugerimos menos de 160."

    return {"valor": description, "comprimento": length, "status": status, "sugestao": sugestao}

def verificar_estrutura_h(soup):
    h1_count = len(soup.find_all('h1'))
    h_data = {
        "h1_count": h1_count,
        "h2_count": len(soup.find_all('h2')),
        "h3_count": len(soup.find_all('h3'))
    }
    
    status = "OK"
    sugestao = "A estrutura H1/H2 está correta."

    if h1_count == 0:
        status = "ERRO"
        sugestao = "H1 ausente. É o título principal da página e deve ser incluído."
    elif h1_count > 1:
        status = "AVISO"
        sugestao = "Múltiplos H1 encontrados. Recomenda-se apenas um H1 por página."
        
    return {"dados": h_data, "status": status, "sugestao": sugestao}

def verificar_alt_text(soup):
    imagens = soup.find_all('img')
    total_imagens = len(imagens)
    sem_alt = 0
    
    for img in imagens:
        if not img.get('alt') or img.get('alt').strip() == "":
            sem_alt += 1

    status = "OK"
    sugestao = "Todas as imagens possuem texto ALT."
    
    if sem_alt > 0:
        status = "AVISO"
        sugestao = f"{sem_alt} de {total_imagens} imagens estão sem texto ALT. Preencher o ALT melhora a acessibilidade e o SEO de imagens."
        
    return {"total_imagens": total_imagens, "sem_alt": sem_alt, "status": status, "sugestao": sugestao}

def verificar_estrutura_url(url, keyword):
    """ Verifica se a URL é amigável, usa hífens, é curta E checa a keyword real. """
    parsed_url = urlparse(url)
    path = parsed_url.path.strip('/').lower()
    keyword_lower = keyword.lower()
    
    erros = []
    
    if keyword_lower and keyword_lower not in path:
        erros.append(f"Keyword principal ('{keyword}') não encontrada no Path da URL.")
    if '_' in path:
        erros.append("A URL usa underscores (_) em vez de hífens (-). Use hífens.")
    if len(path) > 70:
        erros.append(f"O Path da URL é muito longo ({len(path)} caracteres). Mantenha URLs curtas.")
    if parsed_url.netloc.count('.') > 1 and parsed_url.netloc.split('.')[0] != 'www':
        erros.append("A página está em um possível subdomínio. Subpastas são geralmente preferidas para SEO.")
    
    if erros:
        status = "AVISO" if len(erros) < 3 else "ERRO"
        sugestao = "Problemas encontrados na estrutura da URL: " + " | ".join(erros)
    else:
        status = "OK"
        sugestao = "A URL é curta, usa hífens e parece otimizada."
        
    return {"status": status, "sugestao": sugestao}

def verificar_densidade_keywords(soup, keyword):
    """ Verifica a densidade da palavra-chave REAL fornecida pelo usuário. """
    
    if not keyword:
        return {"status": "AVISO", "sugestao": "Palavra-chave não fornecida. Análise de densidade ignorada."}
        
    keyword_lower = keyword.lower()
    
    page_text = soup.get_text().lower()
    
    for script_or_style in soup(['script', 'style']):
        script_or_style.decompose()
    
    keyword_count = page_text.count(keyword_lower)
    
    status = "AVISO"
    sugestao = f"A Keyword ('{keyword}') aparece {keyword_count} vezes. Ideal seria 2-5 para evitar over-optimization."
    
    if keyword_count >= 2 and keyword_count <= 5:
        status = "OK"
        sugestao = f"A Keyword ('{keyword}') aparece {keyword_count} vezes. Densidade dentro do recomendado."
    elif keyword_count > 5:
        status = "AVISO"
        sugestao = f"A Keyword ('{keyword}') aparece {keyword_count} vezes. Potencialmente over-optimized (muita repetição)."
    elif keyword_count == 0:
        status = "ERRO"
        sugestao = f"A Keyword ('{keyword}') não aparece no corpo do texto da página!"
        
    return {"contagem": keyword_count, "status": status, "sugestao": sugestao}

def verificar_over_optimization(soup):
    """ Checa a contagem de palavras (Word Count), sinal de conteúdo fino (low word count). """
    text = soup.get_text()
    word_count = len(re.findall(r'\b\w+\b', text))
    
    status = "AVISO"
    sugestao = f"A página tem {word_count} palavras. Conteúdo abaixo de 300 palavras é considerado 'fino' pelo Google."
    
    if word_count > 300:
        status = "OK"
        sugestao = f"A página tem {word_count} palavras. Conteúdo considerado substancial."
    
    return {"word_count": word_count, "status": status, "sugestao": sugestao}

def verificar_links_quebrados(soup, url_base):
    """ Verifica os primeiros 10 links para erros 4xx/5xx (quebrados). """
    links = soup.find_all('a', href=True)
    links_quebrados = []
    links_para_verificar = links[:10] 

    for link in links_para_verificar:
        href = link['href']
        
        if href.startswith(('#', 'mailto:', 'javascript:')):
            continue

        link_url = urljoin(url_base, href)
        
        try:
            response = requests.head(link_url, timeout=5, allow_redirects=True)
            if response.status_code >= 400:
                links_quebrados.append({"url": link_url, "status": response.status_code})
        except requests.exceptions.RequestException:
             links_quebrados.append({"url": link_url, "status": "Timeout/Erro de Rede"})

    if links_quebrados:
        status = "ERRO"
        sugestao = f"{len(links_quebrados)} links problemáticos encontrados (4xx/5xx ou falha de conexão). Corrija-os."
    else:
        status = "OK"
        sugestao = "Nenhum link quebrado/problemático encontrado nos links verificados."
        
    return {"status": status, "sugestao": sugestao, "quebrados_count": len(links_quebrados)}

def verificar_uso_botoes_link(soup):
    """ Verifica o uso da tag <button> que pode ser substituída por <a> para fins de SEO. """
    
    botoes = soup.find_all('button')
    botoes_sensiveis = []
    
    keywords_navegacao = ['saiba', 'ver', 'detalhes', 'próximo', 'início', 'continuar', 'comprar', 'leia']
    
    for button in botoes:
        button_text = button.text.strip().lower()
        is_form_submit = button.get('type') == 'submit' or button.get('form')
        
        if any(kw in button_text for kw in keywords_navegacao) and not is_form_submit:
             botoes_sensiveis.append(button_text)
             
    if botoes_sensiveis:
        status = "AVISO"
        sugestao = f"Foram encontrados {len(botoes_sensiveis)} botões (tags <button>) com texto de navegação. Recomenda-se substituí-los por tags <a> estilizadas para melhor rastreamento pelo Google."
    else:
        status = "OK"
        sugestao = "Nenhum uso problemático da tag <button> foi detectado. Os links de navegação estão provavelmente usando a tag <a>."
        
    return {"status": status, "sugestao": sugestao, "botoes_encontrados": botoes_sensiveis}


# =============================================================
# MÓDULO DE VERIFICAÇÃO TÉCNICA E AVANÇADA
# =============================================================

def verificar_https(url):
    """ Verifica se a URL utiliza HTTPS. """
    parsed_url = urlparse(url)
    
    if parsed_url.scheme == 'https':
        return {"status": "OK", "sugestao": "O site utiliza o protocolo HTTPS (seguro)."}
    else:
        return {"status": "ERRO", "sugestao": "O protocolo HTTP inseguro foi detectado. Migre para HTTPS."}

def verificar_sitemap(url):
    """ Tenta encontrar o sitemap.xml no domínio raiz. """
    parsed_url = urlparse(url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    sitemap_url = urljoin(base_url, '/sitemap.xml')
    
    try:
        response = requests.head(sitemap_url, timeout=5)
        if response.status_code == 200:
            return {"status": "OK", "sugestao": f"Sitemap encontrado e acessível em {sitemap_url}. Verifique se ele está referenciado no robots.txt."}
        else:
            return {"status": "AVISO", "sugestao": f"Sitemap não encontrado no path /sitemap.xml (Status: {response.status_code})."}
    except requests.exceptions.RequestException:
        return {"status": "ERRO", "sugestao": "Não foi possível acessar o sitemap devido a erro de conexão ou timeout."}

def verificar_tags_canonicais(soup):
    """ Verifica a existência da tag link rel="canonical". """
    canonical_tag = soup.find('link', rel='canonical')
    
    if canonical_tag and canonical_tag.get('href'):
        canonical_url = canonical_tag.get('href')
        
        if canonical_url.strip() == "":
            return {"status": "AVISO", "sugestao": "Tag Canonical vazia encontrada."}
            
        return {"status": "OK", "sugestao": f"Tag Canonical presente: {canonical_url}. Isso ajuda a evitar conteúdo duplicado."}
    else:
        return {"status": "AVISO", "sugestao": "Tag Canonical ausente. Recomenda-se adicionar para evitar problemas de conteúdo duplicado."}

def verificar_tags_ads_pixels(soup):
    """ Verifica scripts comuns de Google Ads (GA) e Meta Pixel (Facebook). """
    
    html_content = str(soup)
    resultados = []
    
    if re.search(r'google-analytics\.com/analytics\.js|googletagmanager\.com/gtm\.js|gtag\(\'config\', \'G-', html_content):
        resultados.append("Google Analytics/GTM (Potencialmente presente)")
        
    if re.search(r'googleadservices\.com/pagead/conversion\.js|googleglobalads\.js', html_content):
        resultados.append("Google Ads Conversion Tracking (Potencialmente presente)")
    
    if re.search(r'connect\.facebook\.net/\w+/fbevents\.js|fbq\(', html_content):
        resultados.append("Facebook/Meta Pixel (Potencialmente presente)")
        
    if resultados:
        return {"status": "AVISO", "sugestao": "Tags de Rastreamento/Métricas encontradas. Verifique a configuração.", "tags_encontradas": resultados}
    else:
        return {"status": "OK", "sugestao": "Nenhuma tag comum de Google Ads, GA ou Meta Pixel foi detectada. Se você usa anúncios/métricas, verifique a instalação."}


def verificar_indexacao_rastreabilidade(soup):
    """ Verifica tags meta robots que podem bloquear a indexação (noindex/nofollow). """
    robots_tag = soup.find('meta', attrs={'name': 'robots'})
    
    if robots_tag:
        content = robots_tag.get('content', '').lower()
        if 'noindex' in content:
            return {"status": "ERRO", "sugestao": f"Tag Meta Robots: 'noindex' encontrada. A página não será indexada. Valor: {content}"}
        if 'nofollow' in content:
            return {"status": "AVISO", "sugestao": f"Tag Meta Robots: 'nofollow' encontrada. Links nesta página não passarão PageRank. Valor: {content}"}
    
    return {"status": "OK", "sugestao": "Nenhuma tag Meta Robots bloqueando a indexação (noindex) foi encontrada."}

def verificar_mobile_friendly(soup):
    """ Verifica se a metatag viewport está presente (requisito básico de responsividade). """
    viewport_tag = soup.find('meta', attrs={'name': 'viewport'})
    
    if viewport_tag:
        content = viewport_tag.get('content', '').lower()
        if 'width=device-width' in content and 'initial-scale' in content:
            return {"status": "OK", "sugestao": "Meta Viewport Tag presente e configurada corretamente. A página deve ser mobile-friendly."}
        else:
            return {"status": "AVISO", "sugestao": f"Meta Viewport Tag encontrada, mas pode estar incompleta. Conteúdo: {content}"}
    
    return {"status": "ERRO", "sugestao": "Meta Viewport Tag ausente. A página provavelmente não é responsiva."}

def verificar_redirecionamento(url_original, response):
    """ Verifica se houve redirecionamento e se a cadeia é longa (problemas de URL). """
    
    if response.history:
        if len(response.history) > 1:
            status = "ERRO"
            sugestao = f"Cadeia de redirecionamento longa ({len(response.history)} saltos). Isso prejudica a velocidade e a passagem de PageRank. URL final: {response.url}"
        else:
            status = "AVISO"
            sugestao = f"Redirecionamento único encontrado ({response.history[0].status_code} para {response.url}). Deve ser verificado."
    else:
        status = "OK"
        sugestao = "Nenhum redirecionamento encontrado. A URL carregou diretamente."
        
    return {"status": status, "sugestao": sugestao, "saltos": len(response.history)}

def verificar_render_blocking(soup):
    """ Verifica scripts e CSS que podem bloquear a renderização (Render Blocking). """
    blocking_files = []
    
    css_links = soup.find_all('link', rel='stylesheet')
    for link in css_links:
        media = link.get('media', '').lower()
        if 'print' not in media and 'defer' not in link.attrs:
            blocking_files.append({"tipo": "CSS", "url": link.get('href', 'N/A')})
            
    js_scripts = soup.find_all('script', src=True)
    for script in js_scripts:
        if not script.get('async') and not script.get('defer') and script.get('src') and script.get('src').strip():
             blocking_files.append({"tipo": "JS", "url": script.get('src', 'N/A')})
             
    if blocking_files:
        status = "AVISO"
        sugestao = f"Foram encontrados {len(blocking_files)} arquivos JS/CSS que podem bloquear a renderização. Considere usar 'defer', 'async' ou 'preload'."
    else:
        status = "OK"
        sugestao = "Nenhum recurso óbvio de bloqueio de renderização encontrado (JS/CSS externo está otimizado)."
        
    return {"status": status, "sugestao": sugestao, "arquivos_bloqueadores": blocking_files}

def verificar_schema_markup(soup):
    """ Verifica a presença de Schema Markup (Dados Estruturados JSON-LD). """
    schema_tags = soup.find_all('script', type='application/ld+json')
    
    if schema_tags:
        schema_types = []
        for tag in schema_tags:
            try:
                if tag.string and '"@type"' in tag.string:
                    type_match = re.search(r'"@type"\s*:\s*"([^"]+)"', tag.string)
                    if type_match and type_match.group(1) not in schema_types:
                        schema_types.append(type_match.group(1))
            except:
                continue
                
        status = "OK"
        sugestao = f"Dados Estruturados JSON-LD encontrados. Tipos: {', '.join(schema_types)}. Verifique a validação no Google Rich Results Test."
    else:
        status = "AVISO"
        sugestao = "Nenhum Schema Markup JSON-LD (dados estruturados) foi encontrado. A inclusão pode ajudar a obter Rich Snippets."
        
    return {"status": status, "sugestao": sugestao}

def verificar_conteudo_misto(soup, url_base):
    """ Verifica links e recursos que usam HTTP em uma página HTTPS (Mixed Content). """
    
    if not url_base.startswith('https://'):
        return {"status": "N/A", "sugestao": "A página não é HTTPS; a verificação de Conteúdo Misto não é aplicável."}
        
    mixed_content = []
    
    for tag in soup.find_all(src=re.compile(r'^http://', re.IGNORECASE)) + soup.find_all(href=re.compile(r'^http://', re.IGNORECASE)):
        
        if tag.name == 'a' and urlparse(tag.get('href')).netloc != urlparse(url_base).netloc:
            continue
            
        url_insegura = tag.get('src') or tag.get('href')
        if url_insegura:
             mixed_content.append({"tag": tag.name, "url_insegura": url_insegura})

    if mixed_content:
        status = "ERRO"
        sugestao = f"Conteúdo Misto (Mixed Content) encontrado! {len(mixed_content)} recurso(s) carregando via HTTP em uma página HTTPS. Isso afeta a segurança e o ranqueamento."
    else:
        status = "OK"
        sugestao = "Nenhum Conteúdo Misto inseguro detectado. Todos os recursos parecem estar carregando via HTTPS."

    return {"status": status, "sugestao": sugestao, "inseguros_encontrados": len(mixed_content)}

def verificar_acessibilidade_basica(soup):
    """ Verifica heurísticas básicas de acessibilidade/legibilidade (tamanho da fonte). """
    
    font_issues = []
    
    # Busca por estilos inline ou tags que sugiram tamanhos de fonte muito pequenos (tipicamente <= 12px)
    small_font_tags = soup.find_all(style=re.compile(r'font-size:\s*(?:10|11|12)px', re.IGNORECASE))
    
    small_font_tags.extend(soup.find_all('small'))
    obsolete_tags = soup.find_all('font')
    
    if small_font_tags:
        font_issues.append(f"{len(small_font_tags)} tags com tamanho de fonte muito pequeno (<small> ou <= 12px inline) foram encontradas.")
        
    if obsolete_tags:
        font_issues.append(f"{len(obsolete_tags)} tags <font> obsoletas encontradas. Use CSS para estilo.")
        
    if font_issues:
        status = "AVISO"
        sugestao = "Problemas de legibilidade (acessibilidade) detectados. Fontes muito pequenas ou uso de tags obsoletas dificultam a leitura e a experiência do usuário. " + " | ".join(font_issues)
    else:
        status = "OK"
        sugestao = "Nenhuma falha crítica de legibilidade (tamanho de fonte ou tags obsoletas) foi detectada."
        
    return {"status": status, "sugestao": sugestao, "issues_count": len(font_issues)}


# =============================================================
# MÓDULO DE VERIFICAÇÃO PAGESPEED INSIGHTS (V16 CORRIGIDA)
# =============================================================

def analisar_pagespeed(url):
    """ Faz a requisição à API PageSpeed Insights e extrai métricas importantes. """
    
    if not PAGESPEED_API_KEY:
        return {"status": "AVISO", "sugestao": "Chave da API PageSpeed ausente. Verificação ignorada. Defina PAGESPEED_API_KEY no .env."}

    # URL CORRIGIDA: Usa 'pagespeedonline'
    api_url = f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url={url}&key={PAGESPEED_API_KEY}&strategy=mobile"
    
    try:
        response = requests.get(api_url, timeout=30) 
        response.raise_for_status() 
        data = response.json()
        
        # --- 1. Extração da Pontuação e Métricas Principais (Lab Data) ---
        performance_score = data.get('lighthouseResult', {}).get('categories', {}).get('performance', {}).get('score')
        metrics = data.get('lighthouseResult', {}).get('audits', {}).get('metrics', {}).get('details', {}).get('items', [{}])[0]
        
        pagespeed_metrics = {
            "score": int(performance_score * 100) if performance_score is not None else "N/A",
            "LCP": metrics.get('largestContentfulPaint', 'N/A'),
            "TBT": metrics.get('totalBlockingTime', 'N/A'),
            "CLS": metrics.get('cumulativeLayoutShift', 'N/A'),
            "FCP": metrics.get('firstContentfulPaint', 'N/A'),
        }
        
        # --- 2. Extração de Oportunidades (Top 3) ---
        opportunities = data.get('lighthouseResult', {}).get('audits', {})
        top_opportunities = []
        
        for key, audit in opportunities.items():
            if audit.get('score') is not None and audit.get('score') < 1 and audit.get('details', {}).get('type') == 'opportunity':
                top_opportunities.append({
                    "title": audit.get('title'),
                    "score": int(audit.get('score') * 100),
                    "impact": audit.get('displayValue') 
                })

        top_opportunities.sort(key=lambda x: x['score'])
        
        # --- 3. Resultado Final ---
        return {
            "status": "OK",
            "sugestao": f"Análise PageSpeed Insights (Móvel) concluída. Score: {pagespeed_metrics['score']}.",
            "pagespeed_data": {
                "metrics": pagespeed_metrics,
                "top_opportunities": top_opportunities[:3]
            }
        }

    except requests.exceptions.RequestException as e:
        return {"status": "ERRO", "sugestao": f"Erro ao consultar a API PageSpeed: {e}"}
    except Exception as e:
        return {"status": "ERRO", "sugestao": f"Erro inesperado no processamento do JSON do PageSpeed: {e}"}


# =============================================================
# MÓDULO PRINCIPAL DE AUDITORIA (V16)
# =============================================================

def analisar_seo_completo(url, keyword):
    """ Função que orquestra todas as análises, incluindo a API PageSpeed. """
    resultados = {
        "url_analisada": url,
        "keyword_analisada": keyword,
        "status": "sucesso",
        "erros": [],
        "verificacoes_seo": {}
    }

    try:
        headers = {'User-Agent': 'SEO Audit Bot V16'}
        response = requests.get(url, headers=headers, timeout=10, allow_redirects=True) 
        response.raise_for_status() 

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # --- V16: CHAMADA DA API PAGESPEED ---
        resultados["verificacoes_seo"]["pagespeed_api"] = analisar_pagespeed(url)
        
        # --- Verificações On-Page e Conteúdo ---
        resultados["verificacoes_seo"]["titulo"] = verificar_titulo(soup)
        resultados["verificacoes_seo"]["meta_description"] = verificar_meta_description(soup)
        resultados["verificacoes_seo"]["estrutura_h"] = verificar_estrutura_h(soup)
        resultados["verificacoes_seo"]["alt_text_imagens"] = verificar_alt_text(soup)
        resultados["verificacoes_seo"]["estrutura_url"] = verificar_estrutura_url(url, keyword)
        resultados["verificacoes_seo"]["uso_botoes_link"] = verificar_uso_botoes_link(soup) 
        resultados["verificacoes_seo"]["densidade_keywords"] = verificar_densidade_keywords(soup, keyword)
        resultados["verificacoes_seo"]["over_optimization"] = verificar_over_optimization(soup)
        resultados["verificacoes_seo"]["links_quebrados"] = verificar_links_quebrados(soup, url)

        # --- Verificações Técnicas e Avançadas ---
        resultados["verificacoes_seo"]["https"] = verificar_https(url)
        resultados["verificacoes_seo"]["redirecionamento"] = verificar_redirecionamento(url, response)
        resultados["verificacoes_seo"]["sitemap"] = verificar_sitemap(url)
        resultados["verificacoes_seo"]["canonical_tag"] = verificar_tags_canonicais(soup)
        resultados["verificacoes_seo"]["indexacao_rastreabilidade"] = verificar_indexacao_rastreabilidade(soup)
        resultados["verificacoes_seo"]["mobile_friendly_viewport"] = verificar_mobile_friendly(soup)
        resultados["verificacoes_seo"]["tags_ads_pixels"] = verificar_tags_ads_pixels(soup)
        resultados["verificacoes_seo"]["render_blocking"] = verificar_render_blocking(soup)
        resultados["verificacoes_seo"]["schema_markup"] = verificar_schema_markup(soup)
        resultados["verificacoes_seo"]["conteudo_misto"] = verificar_conteudo_misto(soup, url)
        resultados["verificacoes_seo"]["acessibilidade_basica"] = verificar_acessibilidade_basica(soup)


    except requests.exceptions.RequestException as e:
        resultados["status"] = "erro_scraping"
        resultados["erros"].append(f"Erro ao acessar a URL ou timeout: {e}")

    return resultados

# =============================================================
# ROTAS DA APLICAÇÃO
# =============================================================

@app.route('/', methods=['GET'])
def index():
    """ Rota para exibir o formulário de entrada. """
    return render_template('index.html')


@app.route('/auditoria', methods=['POST'])
def auditoria_seo():
    """ Rota para receber os dados do formulário e executar a análise. """
    
    url_param = request.form.get('url')
    keyword_param = request.form.get('keyword')

    if not url_param:
        return render_template('index.html', erro="Por favor, forneça uma URL para análise."), 400
    
    if not keyword_param:
        keyword_param = "" 

    if not re.match(r'https?://', url_param):
        url_param = 'https://' + url_param
    
    # 1. Executa a auditoria completa
    resultado_auditoria = analisar_seo_completo(url_param, keyword_param) 
    
    # 2. Prepara o resultado para o template
    final_results = {
        "url_analisada": resultado_auditoria["url_analisada"],
        "keyword_analisada": resultado_auditoria["keyword_analisada"],
        "status_geral": resultado_auditoria["status"],
        "verificacoes": resultado_auditoria["verificacoes_seo"],
        "erros_e_avisos": resultado_auditoria["erros"]
    }
    
    # 3. Renderiza o template de resultado com os dados
    return render_template('resultado.html', resultados=final_results)


if __name__ == '__main__':
    print("Iniciando o Servidor Flask. Auditoria SEO (V16 - FINAL com PageSpeed).")
    # Use app.run() no ambiente local. No Heroku/Render, o Gunicorn cuidará disso.
    app.run(debug=True)