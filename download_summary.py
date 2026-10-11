"""Read existing download metadata without migrating the archive or touching images."""
import sqlite3
from pathlib import Path
def download_summary(root):
    path=Path(root).resolve()/'.toonshelf.sqlite3'
    if not path.is_file():return {}
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=10);db.row_factory=sqlite3.Row
    try:
        rows=db.execute('SELECT e.work_key,COUNT(DISTINCT e.key) AS episodes,MAX(i.last_downloaded) AS last_downloaded FROM episodes e JOIN images i ON i.episode_key=e.key GROUP BY e.work_key').fetchall()
        return {r['work_key']:dict(r) for r in rows}
    except sqlite3.OperationalError:return {}
    finally:db.close()
