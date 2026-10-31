"""프로필 README의 자동 갱신 구간을 다시 쓴다. GitHub Actions가 매일 아침 실행한다.

다시 쓰는 곳은 README의 `<!-- 이름 starts -->`와 `<!-- 이름 ends -->` 사이뿐이다.
야구 예측 저장소는 비공개라, 읽기 권한이 있는 토큰(README_TOKEN)이 없으면 그 줄은 건너뛴다.
"""

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

OWNER = "WindowisPark"
KST = timezone(timedelta(hours=9))
README = Path(__file__).parent / "README.md"
BLOG_URL = "https://windowispark.github.io/commit-blog/blog/{slug}/"

# (저장소, 표시 이름, 예측 기록 파일, 경기 키). 경기 수는 공지한 예측(kind=slate)만 센다
PIPELINES = [
    ("mlb-predictor", "MLB", "data/backup/predictions.ndjson", "game_pk"),
    ("kbo-predictor", "KBO", "data/backup/predictions.ndjson", "game_id"),
    ("npb-predictor", "NPB", "data/backup/predictions.ndjson", "game_id"),
]

CONCLUSION = {"success": "성공", "failure": "실패", "cancelled": "취소", "timed_out": "시간 초과"}


def api(path, raw=False):
    headers = {"Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json"}
    if os.environ.get("GH_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GH_TOKEN']}"
    request = urllib.request.Request(f"https://api.github.com/{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
    return body if raw else json.loads(body)


def kst(timestamp):
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(KST)


def recent_runs(repo, since):
    runs, page = [], 1
    while True:
        batch = api(f"repos/{OWNER}/{repo}/actions/workflows/daily.yml/runs?created=>={since}&per_page=100&page={page}")
        runs += batch["workflow_runs"]
        if len(batch["workflow_runs"]) < 100:
            return runs
        page += 1


def pipeline_line(repo, name, predictions_path, key):
    try:
        workflow = api(f"repos/{OWNER}/{repo}/actions/workflows/daily.yml")
    except urllib.error.HTTPError as error:
        if error.code == 404:  # 토큰 없이는 비공개 저장소가 보이지 않는다
            return None
        raise

    games = set()
    for line in api(f"repos/{OWNER}/{repo}/contents/{predictions_path}", raw=True).splitlines():
        row = json.loads(line)
        if row["kind"] == "slate":
            games.add(row[key])
    parts = [f"**{name}**"]

    if workflow["state"] != "active":
        parts.append("비시즌 중지")
    else:
        since = (datetime.now(KST) - timedelta(days=30)).date().isoformat()
        runs = recent_runs(repo, since)
        completed = [run for run in runs if run["status"] == "completed"]
        if runs:
            last = runs[0]
            state = CONCLUSION.get(last["conclusion"], "실행 중")
            parts.append(f"{kst(last['updated_at']):%m-%d %H:%M} {state}")
        if completed:
            ok = sum(run["conclusion"] == "success" for run in completed)
            parts.append(f"최근 30일 {len(completed)}회 중 {ok}회 성공")

    parts.append(f"예측한 경기 {len(games):,}")
    return "- " + " · ".join(parts)


def devlog_lines(count=3):
    posts = api(f"repos/{OWNER}/commit-blog/contents/src/content/blog")
    # newsroom-ai 글은 사이트 빌드에서 빠지므로(commit-blog의 content.config.ts) 여기서도 세지 않는다
    posts = [p for p in posts if p["name"].endswith(".md") and "-newsroom-ai-" not in p["name"]]
    posts = sorted(posts, key=lambda p: p["name"], reverse=True)
    lines = []
    for post in posts[:count]:
        text = api(f"repos/{OWNER}/commit-blog/contents/{post['path']}", raw=True)
        title = re.search(r'^title:\s*"?(.*?)"?\s*$', text, re.M).group(1)
        date = re.search(r"^pubDate:\s*(\S+)", text, re.M).group(1)
        lines.append(f"- [{title}]({BLOG_URL.format(slug=post['name'][:-3])}) · {date}")
    lines += ["", f"[전체 {len(posts)}편 보기](https://windowispark.github.io/commit-blog/)"]
    return lines


def replace_section(text, name, lines, inline=False):
    # 문장 안에 끼는 구간은 줄을 바꾸면 마크다운이 문단을 끊으므로 같은 줄에 넣는다
    pattern = re.compile(rf"(<!-- {name} starts -->).*?(<!-- {name} ends -->)", re.S)
    if not pattern.search(text):
        raise SystemExit(f"README에 {name} 구간이 없습니다")
    body = "".join(lines) if inline else "\n" + "\n".join(lines) + "\n"
    return pattern.sub(lambda m: f"{m.group(1)}{body}{m.group(2)}", text)


def main():
    pipelines = [line for line in (pipeline_line(*p) for p in PIPELINES) if line]
    text = README.read_text(encoding="utf-8")
    text = replace_section(text, "pipelines", pipelines or ["- 지금은 표시할 실행 기록이 없습니다"])
    text = replace_section(text, "devlog", devlog_lines())
    text = replace_section(text, "updated", [f"{datetime.now(KST):%Y-%m-%d %H:%M} KST"], inline=True)
    README.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
