# Documentação Técnica: KPI-12 (Exposição a Risco Climático)

**Projeto:** Portal de Sócios OZ
**Indicador:** KPI-12 · TR · Exposição a Risco Climático
**Objetivo:** Mensurar e classificar o nível de risco diário das granjas de aves e suínos frente a eventos climáticos adversos (estresse térmico, secas prolongadas e chuvas intensas), visando ações preventivas de manejo e infraestrutura.

---

## 1. Fonte de Dados e Processamento (ETL)

A automação coleta dados diários da **API NASA POWER** (catálogo de Agroclimatologia), que fornece medições via satélite com base na geolocalização exata (Latitude e Longitude) de cada unidade, dispensando a necessidade de estações meteorológicas físicas próximas.

### 1.1 Variáveis Coletadas

* `T2M_MAX`: Temperatura Máxima a 2 metros (°C)
* `T2M_MIN`: Temperatura Mínima a 2 metros (°C)
* `RH2M`: Umidade Relativa a 2 metros (%)
* `PRECTOTCORR`: Precipitação Total Corrigida (mm/dia)

### 1.2 Tratamento de Anomalias (Missing Data)

A API da NASA retorna o valor `-999.0` quando há falha na leitura do satélite. O script realiza o seguinte tratamento para garantir a continuidade da série temporal:

1. Substituição de `-999.0` por `Nulo (NaN)`.
2. **Interpolação Linear:** O sistema preenche o dado faltante calculando a média entre o dia anterior e o dia seguinte válido, isolando o cálculo por `ID_Granja` para evitar cruzamento de dados entre localidades diferentes.

---

## 2. Metodologia de Cálculo (Regras de Negócio)

O índice final varia de **0 a 100** e é composto por três pilares de risco.

### 2.1 Pilar 1: Estresse Térmico (Peso: 50%)

Calculado através do **THI (Índice de Temperatura e Umidade)**, que avalia a sensação térmica real do animal. A fórmula matemática aplicada é:

$$THI = (0.8 \times T2M\_MAX) + \left(\frac{RH2M}{100} \times (T2M\_MAX - 14.4)\right) + 46.4$$

Como a fisiologia termorregulatória de aves e suínos difere severamente, os gatilhos de risco são separados por espécie:

| Classificação | Nota de Risco | THI - Aves (Frangos) | THI - Suínos |
| --- | --- | --- | --- |
| **Conforto** | 0 | < 70 | < 72 |
| **Alerta** | 50 | 70 a 75 | 72 a 78 |
| **Perigo** | 80 | 76 a 81 | 79 a 83 |
| **Emergência** | 100 | $\geq$ 82 | $\geq$ 84 |

### 2.2 Pilar 2: Seca / Déficit Hídrico (Peso: 30%)

O risco de desabastecimento de água (bebedouros e lavagem) não é medido por um único dia sem chuva, mas pelo acumulado recente.

* **Métrica:** Soma móvel da precipitação (`PRECTOTCORR`) dos **últimos 15 dias** para a respectiva granja.

| Classificação | Nota de Risco | Volume Acumulado (15 dias) |
| --- | --- | --- |
| **Normal** | 0 | > 20 mm |
| **Alerta** | 50 | Entre 5 mm e 20 mm |
| **Seca Severa** | 100 | < 5 mm |

### 2.3 Pilar 3: Chuva Intensa (Peso: 20%)

Mede o risco físico à infraestrutura da granja (destelhamento, alagamento) e à logística (bloqueio de acesso para caminhões de ração ou transporte de animais).

* **Métrica:** Volume de precipitação (`PRECTOTCORR`) em 24 horas.

| Classificação | Nota de Risco | Volume Diário (24h) |
| --- | --- | --- |
| **Normal** | 0 | < 30 mm |
| **Chuva Forte** | 50 | Entre 30 mm e 50 mm |
| **Chuva Extrema** | 100 | > 50 mm |

---

## 3. Composição do Índice Final (KPI-12)

Após o cálculo das notas diárias de cada pilar, o script consolida o risco climático final da granja através da média ponderada:

$$KPI\_Risco = (Nota\_Calor \times 0.5) + (Nota\_Seca \times 0.3) + (Nota\_Chuva \times 0.2)$$

O resultado final é arredondado para duas casas decimais, gerando um indicador onde **0 representa risco nulo** e **100 representa colapso climático/emergência severa**.

---

## 4. Estrutura de Saída para o Banco de Dados

A rotina de ETL gera uma tabela fato consolidada pronta para consumo do front-end do Portal de Sócios OZ. A estrutura de dados (`Schema`) exportada é a seguinte:

* `Data`: Data da medição (YYYYMMDD).
* `ID_Granja`: Identificador único da propriedade.
* `Tipo`: Espécie alojada (Aves ou Suinos).
* `T2M_MAX` / `T2M_MIN` / `RH2M` / `PRECTOTCORR`: Variáveis climáticas tratadas.
* `THI`: Índice de Estresse Térmico calculado (Float).
* `Chuva_Acumulada_15d`: Volume acumulado de chuva no período (Float).
* `Nota_Calor` / `Nota_Seca` / `Nota_Chuva`: Pontuações individuais dos pilares (Inteiros: 0, 50, 80 ou 100).
* **`KPI_Risco`**: Indicador final consolidado (Float: 0.00 a 100.00).

Para a renderização visual no portal, recomenda-se que a equipe de UX utilize alertas com base no `KPI_Risco` (ex: Verde para < 30, Amarelo para 30 a 60, e Vermelho para > 60), além de disponibilizar um gráfico de tendência temporal (`Line Chart`) permitindo ao sócio da OZ visualizar como o estresse térmico variou ao longo do período.

# Sobre a API NASA POWER - https://power.larc.nasa.gov/
A escolha da fonte de dados climáticos é crítica para a precisão do cálculo de stress térmico e risco hídrico nas propriedades. A adoção da API NASA POWER (Prediction of Worldwide Energy Resources) apresenta vantagens estruturais e operacionais substanciais quando comparada a fontes oficiais locais (como INMET e ANA) ou modelos complexos de reanálise em bruto.

## 1. Precisão Geográfica Absoluta (Microclima Real)

* **NASA POWER:** Calcula as variáveis climáticas para **qualquer coordenada exata** (Latitude e Longitude) utilizando satélites e modelação numérica global. O risco climático é medido exatamente em cima do telhado da granja.
* **INMET e ANA:** Dependem exclusivamente da localização das suas estações físicas. Se a granja estiver localizada a 50 km da estação mais próxima, os dados de chuva e temperatura registados não refletirão o clima real enfrentado pelos animais, tornando o KPI impreciso.

## 2. Continuidade da Série Histórica (Alta Disponibilidade)

* **NASA POWER:** Fornece um histórico contínuo e sem interrupções.
* **Estações Locais:** Ocorrem frequentemente falhas de hardware, quebra de sensores ou falta de comunicação, gerando "buracos" de dados (dias ou meses sem informação) que quebram a lógica de cálculo de médias e acumulados no BI.

## 3. Foco Agroclimatológico Integrado

* A API da NASA possui um catálogo específico para agricultura (`community=AG`), que já entrega as variáveis processadas no formato ideal (Temperaturas Máxima/Mínima, Humidade Relativa e Precipitação Corrigida), dispensando o trabalho de engenharia de dados pesado exigido por outros satélites ou modelos de reanálise brutos (como o ERA5). Além disso, a API é gratuita e não exige gestão de API Keys.

## 4. Janela de Atualização (Nota sobre o Delay)

Apesar da superioridade na granularidade e estabilidade, a arquitetura deste sistema exige uma adaptação no consumo dos dados pelo portal de negócios. **Por se tratar de um processamento global de imagens de satélite e cruzamento de modelos climáticos, a NASA tem um "delay" (atraso) de 5 a 7 dias para consolidar e disponibilizar os dados na API.**

* **Recomendação para o Portal:** A arquitetura do dashboard e a atualização da base de dados devem ser configuradas para refletir a realidade climática em **D-7** (analisando o risco consolidado da semana anterior).