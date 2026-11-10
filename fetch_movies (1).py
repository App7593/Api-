import json, subprocess

# API key വേണ്ട: yt-dlp ഉപയോഗിച്ച് YouTube-ൽ തിരയുന്നു.
# വിഭാഗം -> തിരച്ചിൽ വാക്ക്. ഇഷ്ടം പോലെ മാറ്റാം/ചേർക്കാം.
QUERIES = {
    "ട്രെൻഡിങ്": "malayalam full movie",
    "കോമഡി": "malayalam comedy full movie",
    "ത്രില്ലർ": "malayalam thriller full movie",
    "ഫാമിലി": "malayalam family full movie",
    "ആക്ഷൻ": "malayalam action full movie",
}
MIN_SECONDS = 3600  # ഒരു മണിക്കൂറിൽ കുറഞ്ഞ വീഡിയോകൾ ഒഴിവാക്കും

def search(q):
    out = subprocess.run(
        ["yt-dlp", "--flat-playlist", "--dump-json", "--no-warnings", "ytsearch30:" + q],
        capture_output=True, text=True, timeout=180)
    items = []
    for line in out.stdout.splitlines():
        try:
            items.append(json.loads(line))
        except Exception:
            pass
    return items

movies, seen = [], set()
for cat, q in QUERIES.items():
    try:
        items = search(q)
    except Exception as e:
        print("failed:", q, e)
        continue
    for i in items:
        vid, dur = i.get("id"), i.get("duration") or 0
        if not vid or vid in seen or dur < MIN_SECONDS:
            continue
        seen.add(vid)
        movies.append({
            "id": vid,
            "title": i.get("title", ""),
            "year": "",
            "category": cat,
            "poster": "https://i.ytimg.com/vi/%s/hqdefault.jpg" % vid,
            "desc": i.get("channel") or i.get("uploader") or "",
        })

# ഒന്നും കിട്ടിയില്ലെങ്കിൽ പഴയ movies.json മാറ്റരുത്
if movies:
    with open("movies.json", "w", encoding="utf-8") as f:
        json.dump(movies, f, ensure_ascii=False, indent=1)
    print("saved", len(movies), "movies")
else:
    raise SystemExit("no results; keeping old movies.json")
