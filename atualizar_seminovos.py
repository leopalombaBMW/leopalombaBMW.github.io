"""Atualiza os seminovos do site do Léo a partir de grandbrasil.com.br.
- Pega todos os seminovos publicados (wp-json) e fica só com as lojas BMW Alphaville e BMW Vila Leopoldina.
- Ignora motos (Motorrad).
- Baixa as fotos para fotos/<slug>/ (as URLs do CDN expiram, por isso ficam no repositório).
- Mantém o catálogo 0 km (modelos) que já está no estoque.json (atualizado pelo Claude a partir do estoque diário).
Nunca grava em qual loja o carro está."""
import json, os, re, shutil, datetime, concurrent.futures as cf
import requests
from bs4 import BeautifulSoup

BASE = "https://grandbrasil.com.br"
LOJAS = {"BMW Alphaville", "BMW Vila Leopoldina"}
MAX_FOTOS = 12
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (site-vitrine Leo Palomba)"
FUEL = {"HIBRIDO": "Híbrido", "GASOLINA": "Gasolina", "FLEX": "Flex", "DIESEL": "Diesel", "ELETRICO": "Elétrico"}

def links():
    out, p = [], 1
    while True:
        r = S.get(f"{BASE}/wp-json/wp/v2/used-cars", params={"per_page": 100, "page": p, "_fields": "link"}, timeout=60)
        if r.status_code != 200: break
        j = r.json(); out += [x["link"] for x in j]
        if len(j) < 100: break
        p += 1
    return out

def cap(s): return " ".join(w.capitalize() if len(w) > 2 else w.lower() for w in s.split())

def parse(url):
    h = S.get(url, timeout=60).text
    d = BeautifulSoup(h, "html.parser")
    for t in d(["script", "style", "form"]): t.decompose()
    full = re.sub(r"\s+", " ", d.get_text(" "))
    loja = re.search(r"Escolha a concession[aá]ria mais perto de voc[eê] (.+?) Endere[cç]o", full)
    if not loja or loja.group(1).strip() not in LOJAS: return None
    m = re.search(r"Marca (.+?) Modelo (.+?) Vers[aã]o (.+?) Quilometragem ([\d.]+) Combust[ií]vel (.+?) Cor (.+?) Ano (\d{4}/\d{4}) C[aâ]mbio (.+?) Final da placa (\d) Portas (\d)", full)
    if not m: return None
    marca, modelo, versao, km, comb, cor, ano, camb, placa, portas = [x.strip() for x in m.groups()]
    if "MOTORRAD" in url.upper(): return None
    h1 = d.find("h1"); tit = h1.get_text(" ").split("\n")[-1] if h1 else ""
    partes = [p.strip() for p in re.split(r"\s+[–-]\s+", re.sub(r"\s+", " ", tit))]
    preco = re.search(r"por R\$ ([\d.,]+)", full)
    blind = re.search(r"(Blindado [A-Za-zÀ-ú]+) Quilometragem", full)
    fotos = [i.get("src") for i in d.select(".car-galery-loop.mobile amp-img") if i.get("src")]
    if not fotos:
        hero = d.select_one(".single-hero-new-ones amp-img")
        if hero and hero.get("src"): fotos = [hero["src"]]
    slug = url.rstrip("/").split("/")[-1]
    return dict(id="s-" + slug, tipo="seminovo", marca=partes[0].title() if partes and partes[0] not in ("BMW", "MINI", "BYD") else (partes[0] if partes else marca),
                modelo=partes[1] if len(partes) > 1 else modelo, versao=" – ".join(partes[2:]) if len(partes) > 2 else versao,
                preco=float(preco.group(1).replace(".", "").replace(",", ".")) if preco else 0,
                km=int(km.replace(".", "")), combustivel=FUEL.get(comb, comb.title()), cor=cap(cor), ano=ano,
                cambio=camb.capitalize(), final_placa=placa, portas=int(portas),
                blindagem=blind.group(1).replace("Blindado ", "").replace("Carbom", "Carbon") if blind else None,
                _fotos=fotos[:MAX_FOTOS], _slug=slug)

def baixar(c):
    pasta = os.path.join("fotos", c["_slug"]); os.makedirs(pasta, exist_ok=True)
    locais = []
    for i, u in enumerate(c["_fotos"]):
        dest = os.path.join(pasta, f"{i+1}.jpg")
        if not os.path.exists(dest):
            try:
                r = S.get(u, timeout=60)
                if r.status_code == 200 and r.content: open(dest, "wb").write(r.content)
            except Exception: pass
        if os.path.exists(dest): locais.append(dest.replace(os.sep, "/"))
    return locais

def main():
    ls = links(); print("links:", len(ls))
    with cf.ThreadPoolExecutor(6) as ex: carros = [c for c in ex.map(parse, ls) if c]
    print("seminovos BMW:", len(carros))
    if len(carros) < 10: raise SystemExit("Poucos carros encontrados; não vou sobrescrever o estoque.")
    with cf.ThreadPoolExecutor(6) as ex: fotos = list(ex.map(baixar, carros))
    for c, f in zip(carros, fotos):
        c["fotos"] = f; c.pop("_fotos"); c.pop("_slug")
    ativos = {c["id"][2:] for c in carros}
    if os.path.isdir("fotos"):
        for p in os.listdir("fotos"):
            if p not in ativos and not p.startswith("0km"): shutil.rmtree(os.path.join("fotos", p), ignore_errors=True)
    est = json.load(open("estoque.json", encoding="utf-8")) if os.path.exists("estoque.json") else {"veiculos": []}
    json.dump({"atualizado": datetime.date.today().isoformat(), "modelos": est.get("modelos", []), "veiculos": carros},
              open("estoque.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

if __name__ == "__main__":
    main()
