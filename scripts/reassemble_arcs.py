"""Зшити сегменти довгих зустрічей у фінальні JSON (1 файл = 1 зустріч).

Читає вихід воркфлоу `cairnwise-long-arcs` (segments[]), групує за (project, meeting_id),
сортує за seg, конкатенує turns, призначає стабільні Speaker-мітки за голосом (перша поява),
пише data/projects/<project>/meetings/<meeting_id>.json. Перед записом чистить старі *.json
у задіяних проєктах (заміняємо короткі чернетки на канонічні m01..m10 арки).

Usage:  python scripts/reassemble_arcs.py <workflow_output_file.json>
(output_file — результат Workflow; шукай у tasks/<id>.output або task-notification result)
"""
import json, os, sys, glob, collections

DST_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "projects")


def find_key(obj, key):
    if isinstance(obj, dict):
        if isinstance(obj.get(key), list):
            return obj[key]
        for v in obj.values():
            r = find_key(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_key(v, key)
            if r is not None:
                return r
    elif isinstance(obj, str):
        s = obj.strip()
        if s.startswith("{") and key in s:
            try:
                return find_key(json.loads(s), key)
            except Exception:
                return None
    return None


def main():
    if len(sys.argv) < 2:
        print("usage: python scripts/reassemble_arcs.py <workflow_output.json>")
        return 1
    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)
    segs = find_key(data, "segments") or []
    print(f"segments found: {len(segs)}")

    g = collections.defaultdict(lambda: {"meeting_type": None, "segs": {}})
    projects = set()
    for s in segs:
        k = (s["project"], s["meeting_id"])
        g[k]["meeting_type"] = s.get("meeting_type")
        g[k]["segs"][s["seg"]] = s["turns"]
        projects.add(s["project"])

    for proj in projects:  # clear short drafts before writing canonical arcs
        for old in glob.glob(os.path.join(DST_ROOT, proj, "meetings", "*.json")):
            os.remove(old)

    total_turns = 0
    for (proj, mid), v in sorted(g.items()):
        turns = []
        for si in sorted(v["segs"]):
            turns.extend(v["segs"][si])
        vmap, out_turns = {}, []
        for t in turns:
            voice = t["voice"]
            if voice not in vmap:
                vmap[voice] = f"Speaker {len(vmap) + 1}"
            out_turns.append({"speaker": vmap[voice], "voice": voice, "text": t["text"].strip()})
        meeting = {"project": proj, "meeting_id": mid, "meeting_type": v["meeting_type"],
                   "language": "uk", "engine": "uk-tts", "turns": out_turns}
        out_dir = os.path.join(DST_ROOT, proj, "meetings")
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, mid + ".json"), "w", encoding="utf-8") as fo:
            json.dump(meeting, fo, ensure_ascii=False, indent=2)
        total_turns += len(out_turns)
        words = sum(len(t["text"].split()) for t in out_turns)
        print(f"  {proj}/{mid:22} {len(out_turns):3} turns, {len(vmap)} spk, ~{words} words (~{words/150:.0f} min)")

    print(f"\n{len(g)} meetings, {total_turns} turns total")


if __name__ == "__main__":
    raise SystemExit(main())
