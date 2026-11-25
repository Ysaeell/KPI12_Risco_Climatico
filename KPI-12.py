import requests
import pandas as pd
import numpy as np
import time
import os

# ==========================================
# 1. CONFIGURAÇÃO DAS GRANJAS E PERÍODO
# ==========================================
# Descobre o caminho da pasta onde este script Python está salvo
diretorio_script = os.path.dirname(os.path.abspath(__file__))

# Monta o caminho completo para o arquivo CSV
caminho_csv = os.path.join(diretorio_script, 'de_para_granjas_lat_long.csv')

# Carrega a tabela de granjas a partir do arquivo CSV
df_granjas = pd.read_csv(caminho_csv)

# Converte a tabela em uma lista de dicionários
granjas = df_granjas.to_dict('records')

start_date = "20261001"
end_date = "20261014"
variaveis_nasa = "T2M_MAX,T2M_MIN,RH2M,PRECTOTCORR"

# Lista para armazenar os dados extraídos
lista_dados_brutos = []

# ==========================================
# 2. EXTRAÇÃO DOS DADOS (API NASA)
# ==========================================
print("Iniciando extração da NASA POWER...")
for granja in granjas:
    url = f"https://power.larc.nasa.gov/api/temporal/daily/point?parameters={variaveis_nasa}&community=AG&longitude={granja['Lon']}&latitude={granja['Lat']}&start={start_date}&end={end_date}&format=JSON"
    
    try:
        response = requests.get(url)
        data = response.json()
        
        # Pega a parte do dicionário que tem os dados
        clima_dict = data['properties']['parameter']
        
        # Converte para DataFrame
        df_temp = pd.DataFrame(clima_dict)
        df_temp.index.name = 'Data'
        df_temp.reset_index(inplace=True)
        # Adiciona a identificação da granja
        df_temp['ID_Granja'] = granja['ID_Granja']
        df_temp['Tipo'] = granja['Tipo'] 
               
        # Guarda na lista
        lista_dados_brutos.append(df_temp)
        
        print(f"Granja {granja['ID_Granja']} extraída com sucesso.")
    except Exception as e:
        # Tenta pegar a mensagem de erro que a própria NASA enviou
        erro_nasa = data.get('messages', ['Erro desconhecido'])[0] if 'data' in locals() and isinstance(data, dict) else e
        print(f"Erro ao extrair Granja {granja['ID_Granja']} | Lat: {granja['Lat']}, Lon: {granja['Lon']} | Motivo: {erro_nasa}")
    
    # Pausa de 2 segundos para evitar bloqueio da API (Rate Limit)
    time.sleep(2)

# Junta todos os dados em uma única tabela
df = pd.concat(lista_dados_brutos, ignore_index=True)

# ==========================================
# 3. TRATAMENTO DOS DADOS AUSENTES (-999)
# ==========================================
# Ordena por Granja e Data para a interpolação funcionar no tempo correto
df = df.sort_values(by=['ID_Granja', 'Data']).reset_index(drop=True)

colunas_clima = ['T2M_MAX', 'T2M_MIN', 'RH2M', 'PRECTOTCORR']

# Substitui o -999.0 por NaN (Nulo do Pandas)
df[colunas_clima] = df[colunas_clima].replace(-999.0, np.nan)

# Aplica a interpolação linear (Ex: se faltar o dia 2, ele faz a média entre dia 1 e 3)
# O agrupamento por ID_Granja impede que dados de uma granja "vazem" para a outra
for col in colunas_clima:
    df[col] = df.groupby('ID_Granja')[col].transform(
        lambda x: x.interpolate(method='linear').bfill().ffill()
    )

print("Tratamento de valores -999 concluído.")

# ==========================================
# 4. CÁLCULO DOS KPIs E NOTAS DE RISCO
# ==========================================

# Cálculo do THI (Estresse Térmico)
df['THI'] = (0.8 * df['T2M_MAX']) + ((df['RH2M'] / 100) * (df['T2M_MAX'] - 14.4)) + 46.4

# Mapeia as condições considerando tanto o THI quanto o Tipo de Granja
condicoes_calor = [
    # Regras para AVES
    (df['Tipo'] == 'Aves') & (df['THI'] < 70),
    (df['Tipo'] == 'Aves') & (df['THI'] >= 70) & (df['THI'] <= 75),
    (df['Tipo'] == 'Aves') & (df['THI'] >= 76) & (df['THI'] <= 81),
    (df['Tipo'] == 'Aves') & (df['THI'] >= 82),
    
    # Regras para SUÍNOS
    (df['Tipo'] == 'Suinos') & (df['THI'] < 72),
    (df['Tipo'] == 'Suinos') & (df['THI'] >= 72) & (df['THI'] <= 78),
    (df['Tipo'] == 'Suinos') & (df['THI'] >= 79) & (df['THI'] <= 83),
    (df['Tipo'] == 'Suinos') & (df['THI'] >= 84)
]

# As notas (0, 50, 80, 100) aplicadas na mesma ordem das condições acima
notas_calor = [
    0, 50, 80, 100,  # Notas Aves
    0, 50, 80, 100   # Notas Suínos
]

df['Nota_Calor'] = np.select(condicoes_calor, notas_calor, default=0)

# Pontuação: Nota de Chuva Intensa
condicoes_chuva = [
    df['PRECTOTCORR'] < 30,
    (df['PRECTOTCORR'] >= 30) & (df['PRECTOTCORR'] <= 50),
    df['PRECTOTCORR'] > 50
]
notas_chuva = [0, 50, 100]
df['Nota_Chuva'] = np.select(condicoes_chuva, notas_chuva, default=0)

# Pontuação: Nota de Seca (Acumulado de 15 dias)
df['Chuva_Acumulada_15d'] = df.groupby('ID_Granja')['PRECTOTCORR'].transform(
    lambda x: x.rolling(window=15, min_periods=1).sum()
)

condicoes_seca = [
    df['Chuva_Acumulada_15d'] > 20,
    (df['Chuva_Acumulada_15d'] >= 5) & (df['Chuva_Acumulada_15d'] <= 20),
    df['Chuva_Acumulada_15d'] < 5
]
notas_seca = [0, 50, 100]
df['Nota_Seca'] = np.select(condicoes_seca, notas_seca, default=0)

# ==========================================
# 5. KPI FINAL
# ==========================================
# Calcula o risco e arredonda os valores para não sujar o banco de dados
df['KPI_Risco'] = ((df['Nota_Calor'] * 0.5) + (df['Nota_Seca'] * 0.3) + (df['Nota_Chuva'] * 0.2)).round(2)
df['THI'] = df['THI'].round(2)

for col in colunas_clima:
    df[col] = df[col].round(2)

colunas_finais = [
    'Data', 'ID_Granja', 'Tipo', 
    'T2M_MAX', 'T2M_MIN', 'RH2M', 'PRECTOTCORR', 
    'THI', 'Chuva_Acumulada_15d', 
    'Nota_Calor', 'Nota_Seca', 'Nota_Chuva', 
    'KPI_Risco'
]

# Exibir dados finais
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)

print("\nProcessamento finalizado. Amostra dos dados prontos:")
print(df[colunas_finais].head(50))

# ==========================================
# 6. EXPORTAÇÃO DOS DADOS
# ==========================================

# 1. Mostra um resumo rápido no terminal para confirmar quantas granjas e linhas foram processadas
total_granjas = df['ID_Granja'].nunique()
total_linhas = len(df)
print(f"\nSucesso! O script processou {total_linhas} linhas referentes a {total_granjas} granjas.")

# 2. Exporta a tabela completa para um arquivo CSV na mesma pasta do script
caminho_exportacao = os.path.join(diretorio_script, 'KPI12_Risco_Climatico_Final.csv')
df[colunas_finais].to_csv(caminho_exportacao, sep=';', decimal=',', index=False, encoding='utf-8-sig')

print(f"Arquivo completo salvo em: {caminho_exportacao}")