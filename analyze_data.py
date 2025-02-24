import requests
import json
from urllib.parse import quote
from traceback import print_exc as tb
from bs4 import BeautifulSoup
from google import genai
from google.generativeai import protos
from google.genai import types
import time
import re

def load_api_keys():
    try:
        with open("keys.json", "r") as f:
            return json.load(f)
    except Exception as e:
        tb()
        return {}

# NEW: Initialize the client and model ID using the new syntax
client = genai.Client(
    api_key=load_api_keys()["gemini"],
)

model_id = "gemini-2.0-flash"

issues = {
    "DEI_L": "DEI in leadership",
    "DEI_H": "DEI in hiring",
    "QUEER": "LGBTQ support",
    "BIPOC": "BIPOC support",
    "PAY": "Fair wages",
    "ENV": "Low environmental impact",
    "CHARITY": "Charitable donations and support",
    "POLI": "Progressive or Democratic political engagement"
}

TEST_MODE = 'true'  # Set to 'true' to use mock data for API calls

issues_funcs: list[protos.FunctionDeclaration] = []

for issue_id, issue_desc in issues.items():
    issues_funcs.append(protos.FunctionDeclaration(
      name=f"{issue_id}_INDEX",
      description=(
          f"""Given the article(s) in the prompt, indicate how strongly the article(s) relate to \
"{issue_desc}" in regard to the company defined in the prompt as COMPANY NAME. \
This weight should be a value from 0-100, with 0 meaning it doesn't mention that issue in regards to the company at all, \
and 100 means that issue as it relates to the company is the only thing the article(s) talk about. \
Then, score the company in the \"{issue_desc}\" category, from 1-100, given the content of the article, \
where 50 means a net-neutral impact, 100 means that the company is a world leader in the category, \
and 0 means they're doing extensive, lasting damage. If the significance weight is 0, don't include the score."""
      ),
      parameters=protos.Schema(
        type="OBJECT",
        required=["significance"],
        properties={
          "significance": protos.Schema(
            type='NUMBER',
          ),
          "score": protos.Schema(
            type='NUMBER',
          ),
        },
      ),
    ))

issues_tool = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="multiply",
        description="Returns a * b.",
        parameters=types.Schema(
            properties={
                'a': types.Schema(type='NUMBER'),
                'b': types.Schema(type='NUMBER'),
            },
            type='OBJECT',
        ),
    )
])

grounding_tool = types.Tool(google_search=types.GoogleSearch())

def ask_about_article(input_text: str):
    try:
        response = client.models.generate_content(
            model=model_id,
            contents=input_text,
            config=types.GenerateContentConfig(
                tools=[issues_tool],
            )
        )
    except Exception as e:
        tb()
        return {}
    output = {}
    try:
        for part in response.candidates[0].content.parts:
            try:
                data = json.loads(part.text)
                for key, value in data.items():
                    output[key] = value  # Expected format: {issue_id: [significance, score]}
            except json.JSONDecodeError:
                pass
    except Exception as e:
        tb()
    return output

def extract_text_from_html(html_string):
    try:
        soup = BeautifulSoup(html_string, "html.parser")
        text = soup.get_text(separator='\n', strip=True)
        return text
    except Exception as e:
        tb()
        return ""

def get_test_fmp_data() -> dict:
    return {
        "ENV": [0.8, 0.75],
        "PAY": [0.5, 0.65]
    }

def get_test_google_data(company_name: str) -> dict:
    if company_name:
        return {
            "DEI_L": [50, 20],
            "DEI_H": [60, 30],
            "QUEER": [70, 40],
            "BIPOC": [80, 50],
            "PAY": [90, 60]
        }
    return {}

def get_test_gemini_response(company_name: str) -> dict:
    if company_name:
        return {
            "DEI_L": [50, 75],
            "DEI_H": [50, 80],
            "QUEER": [50, 70],
            "BIPOC": [50, 65],
            "PAY": [50, 60],
            "ENV": [50, 85]
        }
    return {}

def get_test_competitors(company_name: str) -> list:
    test_competitors = {
        "Apple": ["Samsung", "Microsoft", "Google"],
        "Google": ["Microsoft", "Apple", "Amazon"],
        "Meta": ["Twitter", "TikTok", "LinkedIn"]
    }
    return test_competitors.get(company_name, ["Competitor 1", "Competitor 2", "Competitor 3"])

def aggregate_metrics(metrics_list: list[dict[str, list[float, float]]]) -> dict:
    aggregated_metrics = {}
    
    # Combine all metrics into a single structure
    combined_metrics = {}
    for metrics in metrics_list:
        for issue_id, data in metrics.items():
            if issue_id not in combined_metrics:
                combined_metrics[issue_id] = []
                
            # Ensure data is in correct format [weight, score]
            if isinstance(data, list) and len(data) == 2:
                try:
                    weight, score = float(data[0]), float(data[1])
                    combined_metrics[issue_id].append([weight, score])
                except (ValueError, TypeError):
                    continue
    
    # Calculate weighted averages for each issue
    for issue_id, data_points in combined_metrics.items():
        if not data_points:
            continue
        
        try:
            total_weight = sum(point[0] for point in data_points)
            if total_weight <= 0:
                continue
                
            weighted_sum = sum(point[0] * point[1] for point in data_points)
            final_score = weighted_sum / total_weight
            
            aggregated_metrics[issue_id] = {
                "score": round(final_score, 3),
                "confidence": round(total_weight, 3)
            }
        except (IndexError, TypeError):
            continue
    
    return aggregated_metrics

def data_fmp(symbol: str) -> dict:
    if TEST_MODE:
        return get_test_fmp_data()
    api_keys = load_api_keys()
    if "financialmodelingprep" not in api_keys:
        tb()
        return {}
    key = api_keys["financialmodelingprep"]
    url = f"https://financialmodelingprep.com/stable/esg-disclosures?symbol={symbol}&apikey={key}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        json_data = response.json()
        if not json_data:
            tb()
            return {}
        data = json_data[0]
        output = {
            "ENV": [1, data.get("environmentalScore", 0) / 100],
            "PAY": [0.5, data.get("socialScore", 0) / 100]
        }
        return output
    except Exception as e:
        tb()
        return {}

def data_google(company_name: str) -> dict[str, list[float, float]]:
    if TEST_MODE:
        return get_test_google_data(company_name)
    
    api_keys = load_api_keys()
    if "google" not in api_keys or "gemini" not in api_keys:
        tb()
        return {}
    key = api_keys["google"]
    base_url = "https://www.googleapis.com/customsearch/v1?key={key}&cx=c1bd8c831439c48db&q={query}"
    responses = {}
    for issue_id, description in issues.items():
        start_time = time.time()
        query = quote(f"{company_name} {description}")
        final_url = base_url.format(key=key, query=query)
        url_list = []
        try:
            r = requests.get(final_url, timeout=10)
            r.raise_for_status()
            result = r.json()
            result_items = result.get("items", [])
            for item in result_items:
                try:
                    link = item.get("link")
                    if not link:
                        continue
                    article_response = requests.get(link, timeout=10)
                    if not article_response.ok:
                        continue
                    text_response = extract_text_from_html(article_response.text)
                    if text_response:
                        url_list.append(text_response)
                except Exception as e:
                    tb()
        except Exception as e:
            tb()
        elapsed = time.time() - start_time
        if elapsed < 1:
            time.sleep(1 - elapsed)
        responses[issue_id] = url_list
    
    datasets = []
    for issue_id, articles in responses.items():
        if not articles:
            continue
        formatted_articles = [f"ARTICLE {i+1}: {article}" for i, article in enumerate(articles)]
        prompt = f"COMPANY NAME: {company_name}\nARTICLE(S): {' '.join(formatted_articles)}"
        response = ask_about_article(prompt)
        datasets.append({issue_id: response})
    
    return aggregate_metrics(datasets)

def data_grounded_gemini(company_name: str) -> dict[str, float]:
    if TEST_MODE:
        return get_test_gemini_response(company_name)
    
    categoriesList = "{"
    for id, desc in issues.items():
        categoriesList += f'"{id}": "{desc}", '
    try:
        response = client.models.generate_content(
            model=model_id,
            contents=f"Research and score the company \"{company_name}\" in all the \
specified categories you can find information on as described. \
The score should be from 0 to 100, where 50 means no impact, 100 means that the company is a \
world leader in the category, and 0 means they're doing extensive, lasting damage. \
Your output should be a dict where the keys are the category IDs and the values are the scores. Wrap this dict in backticks. \
categories: \n{categoriesList}" + "}",
            config=types.GenerateContentConfig(
                tools=[grounding_tool]
            )
        )
        match: re.Match[str] = re.search(r'\{.*?\}', response.text, re.DOTALL)
        json_str = match.group(0)
        json_output = json.loads(json_str)
        final_output = {}
        for key, value in json_output.items():
            final_output[key] = [50, value]
        return final_output
    except Exception as e:
        tb()
        return {}

def ask_compeditors(company_name: str) -> list:
    if TEST_MODE:
        return get_test_competitors(company_name)
    
    try:
        prompt = (
            f"COMPANY NAME: {company_name}\n"
            "Please list the major competitors of this company. For example, McDonald's competitors are Burger King, Wendy's, Chick-fil-A. "
            "Return the answer as a comma-separated list."
        )
        response = client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["STRING"],
                tools=[grounding_tool],
            )
        )
        compeditors_text = ""
        for part in response.candidates[0].content.parts:
            compeditors_text += part.text
        compeditors = [c.strip() for c in compeditors_text.split(",") if c.strip()]
        return compeditors
    except Exception as e:
        tb()
        return []

def analyze_companies(companies: list[str]):
    all_company_data = {}
    for company in companies:
        print(f"Analyzing {company}...")
        try:
            api_keys = load_api_keys()
            if "gemini" not in api_keys:
                tb()
                continue
        except Exception as e:
            tb()
            continue

        # Get Google search data
        google_data = data_google(company)
        
        # Get FMP data
        fmp_data = data_fmp(company)

        # Get Gemini grounded data
        gemini_response = data_grounded_gemini(company)

        # Aggregate metrics
        metrics = aggregate_metrics([google_data, fmp_data, gemini_response])
        
        # Get competitors
        competitors = ask_compeditors(company)
        
        # Store results
        if metrics:
            all_company_data[company] = {
                "metrics": metrics,
                "competitors": competitors,
                "date": int(time.time())
            }

    return all_company_data

if __name__ == "__main__":
    if TEST_MODE:
        print("[TEST MODE ENABLED] Using mock data for API calls")
    
    companies = [
        "Apple",
        #   "Google",
        #   "Meta",
        #   "Shein",
        #   "Tesla",
        #   "Oufer Jewelry",
        #   "Temu"
    ]

    final_data = analyze_companies(companies)
    print(final_data)
    with open("output_b.json", "w") as f:
        json.dump(final_data, f, indent=2)