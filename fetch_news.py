def load_archive():
    try:
        with open("archive.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def save_archive(archive):
    with open("archive.json", "w", encoding="utf-8") as f:
        json.dump(archive, f, indent=2)
