import argparse
import dateutil.parser
import httpx
import magic
import os
import rich.progress
import time
import json
from atproto import CAR, Client, models
from atproto_client.request import Request
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path

# -------------------------------
# Conversion Functions for CAR
# -------------------------------

def convert_car_to_json_from_car(car, output_json_path):
    """
    Convert a parsed CAR object to JSON and write it to a file.
    """
    blocks = getattr(car, 'blocks', [])
    data = {"blocks": []}
    for block in blocks:
        if hasattr(block, "to_dict"):
            data["blocks"].append(block.to_dict())
        else:
            data["blocks"].append(block.__dict__ if hasattr(block, "__dict__") else str(block))
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    print(f"JSON conversion complete: {output_json_path}")
    return data

def find_blob_file(blob_folder, cid):
    """
    Look for a file in blob_folder that starts with the given CID.
    """
    try:
        for filename in os.listdir(blob_folder):
            if filename.startswith(cid):
                return os.path.join(blob_folder, filename)
    except Exception as e:
        print(f"Error reading blob folder: {e}")
    return None

def generate_html_from_data(data, output_html_path, blob_folder="", cursor_suggestion=""):
    """
    Generate an HTML file with tabs for Posts, Likes, Reposts, and Others.
    If blob_folder is provided, it attempts to display media blobs from that folder.
    Additionally, if cursor_suggestion is not empty, a suggestion message is appended.
    """
    # Categorize blocks based on record type.
    posts = []
    likes = []
    reposts = []
    others = []
    
    for block in data.get("blocks", []):
        if isinstance(block, dict) and "record" in block:
            rec = block["record"]
            rec_type = rec.get("$type", "").lower()
            if "like" in rec_type:
                likes.append(block)
            elif "repost" in rec_type:
                reposts.append(block)
            elif "post" in rec_type or rec_type == "":
                posts.append(block)
            else:
                others.append(block)
        elif isinstance(block, dict) and "cid" in block:
            # Consider blocks with a CID as blobs/other media.
            others.append(block)
        else:
            others.append(block)
    
    html_content = [
        "<html>",
        "<head>",
        "  <meta charset='utf-8'>",
        "  <title>CAR Archive</title>",
        "  <style>",
        "    body { font-family: Arial, sans-serif; padding: 20px; }",
        "    .post { border: 1px solid #ccc; padding: 10px; margin: 10px 0; }",
        "    .tab { overflow: hidden; border-bottom: 1px solid #ccc; }",
        "    .tab button { background-color: inherit; float: left; border: none; outline: none; cursor: pointer; padding: 10px 16px; transition: 0.3s; font-size: 17px; }",
        "    .tab button:hover { background-color: #ddd; }",
        "    .tab button.active { background-color: #ccc; }",
        "    .tabcontent { display: none; padding: 20px 0; }",
        "    .blob { margin: 10px 0; }",
        "    .cursor-suggestion { margin-top: 30px; padding: 10px; border: 1px solid #aaa; background-color: #f9f9f9; }",
        "  </style>",
        "</head>",
        "<body>",
        "  <h1>CAR Archive Contents</h1>",
        "  <div class='tab'>",
        "    <button class='tablinks' onclick=\"openTab(event, 'Posts')\" id='defaultOpen'>Posts</button>",
        "    <button class='tablinks' onclick=\"openTab(event, 'Likes')\">Likes</button>",
        "    <button class='tablinks' onclick=\"openTab(event, 'Reposts')\">Reposts</button>",
        "    <button class='tablinks' onclick=\"openTab(event, 'Others')\">Others</button>",
        "  </div>",
        "  <div id='Posts' class='tabcontent'>",
        "    <h2>Posts</h2>"
    ]
    
    for block in posts:
        html_content.append("<div class='post'>")
        rec = block.get("record", {})
        post_text = rec.get("post", "No content")
        created_at = rec.get("created_at", "Unknown time")
        html_content.append(f"<p><strong>Created at:</strong> {created_at}</p>")
        html_content.append(f"<p>{post_text}</p>")
        # Check for associated blob via CID.
        if "cid" in block and blob_folder:
            cid = block["cid"]
            file_path = find_blob_file(blob_folder, cid)
            if file_path:
                extension = os.path.splitext(file_path)[1].lower()
                if extension in [".jpeg", ".jpg", ".png", ".gif"]:
                    html_content.append(f"<img src='{file_path}' alt='Blob {cid}' style='max-width:100%;'/>")
                else:
                    html_content.append(f"<a href='{file_path}'>Download attachment</a>")
        html_content.append("</div>")
    html_content.append("  </div>")
    
    # Likes tab
    html_content.append("  <div id='Likes' class='tabcontent'>")
    html_content.append("    <h2>Likes</h2>")
    for block in likes:
        html_content.append("<div class='post'>")
        rec = block.get("record", {})
        like_info = rec.get("like", "Like record")
        created_at = rec.get("created_at", "Unknown time")
        html_content.append(f"<p><strong>Created at:</strong> {created_at}</p>")
        html_content.append(f"<p>{json.dumps(like_info)}</p>")
        html_content.append("</div>")
    html_content.append("  </div>")
    
    # Reposts tab
    html_content.append("  <div id='Reposts' class='tabcontent'>")
    html_content.append("    <h2>Reposts</h2>")
    for block in reposts:
        html_content.append("<div class='post'>")
        rec = block.get("record", {})
        repost_info = rec.get("repost", "Repost record")
        created_at = rec.get("created_at", "Unknown time")
        html_content.append(f"<p><strong>Created at:</strong> {created_at}</p>")
        html_content.append(f"<p>{json.dumps(repost_info)}</p>")
        html_content.append("</div>")
    html_content.append("  </div>")
    
    # Others tab
    html_content.append("  <div id='Others' class='tabcontent'>")
    html_content.append("    <h2>Others</h2>")
    for block in others:
        html_content.append("<div class='post'>")
        if isinstance(block, dict) and "cid" in block and blob_folder:
            cid = block["cid"]
            file_path = find_blob_file(blob_folder, cid)
            if file_path:
                extension = os.path.splitext(file_path)[1].lower()
                if extension in [".jpeg", ".jpg", ".png", ".gif"]:
                    html_content.append(f"<p>Media Blob (CID: {cid}):</p>")
                    html_content.append(f"<img src='{file_path}' alt='Blob {cid}' style='max-width:100%;'/>")
                else:
                    html_content.append(f"<p>Media Blob (CID: {cid}): <a href='{file_path}'>Download file</a></p>")
            else:
                html_content.append(f"<p>Blob with CID {cid} not found in blob folder.</p>")
        else:
            html_content.append("<pre>")
            html_content.append(json.dumps(block, indent=4, ensure_ascii=False))
            html_content.append("</pre>")
        html_content.append("</div>")
    html_content.append("  </div>")
    
    # Add the cursor suggestion block if provided.
    if cursor_suggestion:
        html_content.append(f"""
  <div class='cursor-suggestion'>
    <p><strong>Cursor Suggestion:</strong> For future runs, consider using the -c flag with this cursor:</p>
    <p style="font-family: monospace;">{cursor_suggestion}</p>
  </div>
""")
    
    # JavaScript for tab functionality.
    html_content.append("""
  <script>
    function openTab(evt, tabName) {
      var i, tabcontent, tablinks;
      tabcontent = document.getElementsByClassName("tabcontent");
      for (i = 0; i < tabcontent.length; i++) {
        tabcontent[i].style.display = "none";
      }
      tablinks = document.getElementsByClassName("tablinks");
      for (i = 0; i < tablinks.length; i++) {
        tablinks[i].className = tablinks[i].className.replace(" active", "");
      }
      document.getElementById(tabName).style.display = "block";
      evt.currentTarget.className += " active";
    }
    document.getElementById("defaultOpen").click();
  </script>
""")
    
    html_content.append("</body>")
    html_content.append("</html>")
    
    with open(output_html_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(html_content))
    print(f"HTML file generated: {output_html_path}")

# -------------------------------
# Modified HTTP Request with Delay
# -------------------------------

class RequestCustomTimeout(Request):
    def __init__(self, timeout: httpx.Timeout = httpx.Timeout(120), *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._client = httpx.Client(follow_redirects=True, timeout=timeout)
        # Wrap the client's request method to add a 750ms delay for every API call.
        original_request = self._client.request
        def delayed_request(method, url, *args, **kwargs):
            time.sleep(0.75)  # 750 millisecond delay to stay below 5000 API calls per hour rate limit. Does 4800 API calls per hour if running perfectly.
            return original_request(method, url, *args, **kwargs)
        self._client.request = delayed_request

# -------------------------------
# The Original SkeeterDeleter Class
# -------------------------------

class PostQualifier(models.AppBskyFeedDefs.FeedViewPost):
    def is_viral(self, viral_threshold) -> bool:
        if viral_threshold == 0:
            return False
        return self.post.repost_count >= viral_threshold

    def is_stale(self, stale_threshold, now) -> bool:
        if stale_threshold == 0:
            return False
        return dateutil.parser.parse(self.post.record.created_at).replace(tzinfo=timezone.utc) <= now - timedelta(days=stale_threshold)

    def is_protected_domain(self, domains_to_protect) -> bool:
        return hasattr(self.post.embed, "external") and any(uri in self.post.embed.external.uri for uri in domains_to_protect)
        
    def is_self_liked(self) -> bool:
        lc = None
        while True:
            likes = self.client.app.bsky.feed.get_likes(params={
                'uri': self.post.uri,
                'cursor': lc,
                'limit': 100})
            lc = likes.cursor
            if self.client.me.did in [l.actor.did for l in likes.likes] and self.post.author.did == self.client.me.did:
                return True
            if not lc:
                break
        return False
    
    def __init__(self, client : Client):
        super(PostQualifier, self).__init__()
        self._init_PostQualifier(client)
    
    def _init_PostQualifier(self, client : Client):
        self.client = client

    def delete_like(self):
        self.client.delete_like(self.post.viewer.like)

    def remove(self):
        if self.post.author.did != self.client.me.did:
            try:
                self.client.unrepost(self.post.viewer.repost)
            except Exception as e:
                print(f"Failed to unrepost: {self.post} ({e})")
        else:
            try:
                self.client.delete_post(self.post.uri)
            except Exception as e:
                print(f"Failed to delete: {self.post.uri} ({e})")

    @staticmethod
    def to_delete(viral_threshold, stale_threshold, domains_to_protect, now, post):
        if (post.is_viral(viral_threshold) or post.is_stale(stale_threshold, now)) and \
           not post.is_protected_domain(domains_to_protect) and \
           not post.is_self_liked():
            return True
        return False

    @staticmethod
    def to_unlike(stale_threshold, now, post):
        return post.is_stale(stale_threshold, now) and not post.is_self_liked()
    
    @staticmethod
    def cast(client : Client, post : models.AppBskyFeedDefs.FeedViewPost):
        post.__class__ = PostQualifier
        post._init_PostQualifier(client)
        return post

@dataclass
class Credentials:
    login: str
    password: str

    dict = asdict

class SkeeterDeleter:
    def archive_repo(self, now, cursor_suggestion="", **kwargs):
        # Retrieve repository CAR bytes.
        repo = self.client.com.atproto.sync.get_repo(params={'did': self.client.me.did})
        car = CAR.from_bytes(repo)
        clean_user_did = self.client.me.did.replace(":", "_")
        archive_dir = f"archive/{clean_user_did}"
        blob_dir = os.path.join(archive_dir, "_blob")
        Path(blob_dir).mkdir(parents=True, exist_ok=True)
        print("Archiving posts and media...")

        # Download and archive media blobs.
        cursor = None
        print("Downloading and archiving media...")
        blob_cids = []
        while True:
            blob_page = self.client.com.atproto.sync.list_blobs(params={'did': self.client.me.did, 'cursor': cursor})
            blob_cids.extend(blob_page.cids)
            cursor = blob_page.cursor
            if not cursor:
                break
        for cid in rich.progress.track(blob_cids):
            blob = self.client.com.atproto.sync.get_blob(params={'cid': cid, 'did': self.client.me.did})
            file_type = magic.from_buffer(blob, 2048)
            ext = ".jpeg" if file_type == "image/jpeg" else ""
            with open(os.path.join(blob_dir, f"{cid}{ext}"), "wb") as f:
                if self.verbosity == 2:
                    print(f"Saving blob {cid}{ext}")
                f.write(blob)

        # Instead of writing a CAR file, convert it to JSON and HTML.
        clean_now = now.isoformat().replace(":", "_")
        json_path = os.path.join(archive_dir, f"bsky-archive-{clean_now}.json")
        html_path = os.path.join(archive_dir, f"bsky-archive-{clean_now}.html")
        data = convert_car_to_json_from_car(car, json_path)
        generate_html_from_data(data, html_path, blob_folder=blob_dir, cursor_suggestion=cursor_suggestion)
        self.html_path = html_path  # store for reference

    def gather_posts_to_unlike(self, stale_threshold, now, fixed_likes_cursor, **kwargs) -> list:
        cursor = None
        to_unlike = []
        while True:
            posts = self.client.app.bsky.feed.get_actor_likes(params={
                "actor": self.client.me.handle,
                "cursor": cursor,
                "limit": 100
            })
            to_unlike.extend(list(filter(
                partial(PostQualifier.to_unlike, stale_threshold, now),
                map(partial(PostQualifier.cast, self.client), posts.feed)
            )))
            
            # If no new cursor or we've reached a point older than fixed_likes_cursor, stop.
            if cursor == posts.cursor or (fixed_likes_cursor and posts.cursor < fixed_likes_cursor):
                break
            else:
                cursor = posts.cursor
                if self.verbosity > 0:
                    print(f"New likes cursor: {cursor}")
        self.last_likes_cursor = cursor
        return to_unlike

    def gather_posts_to_delete(self, viral_threshold, stale_threshold, domains_to_protect, now, **kwargs) -> list:
        cursor = None
        to_delete = []
        while True:
            posts = self.client.get_author_feed(self.client.me.handle,
                                                cursor=cursor,
                                                filter="from:me",
                                                limit=100)
            delete_test = partial(PostQualifier.to_delete, viral_threshold, stale_threshold, domains_to_protect, now)
            to_delete.extend(list(filter(
                delete_test,
                map(partial(PostQualifier.cast, self.client), posts.feed)
            )))
            cursor = posts.cursor
            if self.verbosity > 0:
                print(f"Posts feed cursor: {cursor}")
            if cursor is None:
                break
        return to_delete

    def batch_unlike_posts(self) -> None:
        if self.verbosity > 0:
            print(f"Unliking {len(self.to_unlike)} post{'' if len(self.to_unlike) == 1 else 's'}")
        for post in rich.progress.track(self.to_unlike):
            if self.verbosity == 2:
                print(f"Unliking: {post.post.record.post} by {post.post.author.handle}, CID: {post.post.cid}")
            post.delete_like()

    def batch_delete_posts(self) -> None:
        if self.verbosity > 0:
            print(f"Deleting {len(self.to_delete)} post{'' if len(self.to_delete) == 1 else 's'}")
        for post in rich.progress.track(self.to_delete):
            if self.verbosity == 2:
                print(f"Deleting: {post.post.record.post} on {post.post.record.created_at}, CID: {post.post.cid}")
            post.remove()
            
    def __init__(self,
                 credentials : Credentials,
                 viral_threshold : int = 0,
                 stale_threshold : int = 0,
                 domains_to_protect : list = [],
                 fixed_likes_cursor : str = None,
                 verbosity : int = 0,
                 autodelete : bool = False):
        self.client = Client(request=RequestCustomTimeout())
        self.client.login(**credentials.dict())

        params = {
            'viral_threshold': viral_threshold,
            'stale_threshold': stale_threshold,
            'domains_to_protect': domains_to_protect,
            'fixed_likes_cursor': fixed_likes_cursor,
            'now': datetime.now(timezone.utc),
        }
        self.verbosity = verbosity
        self.autodelete = autodelete

        # First, gather likes to get the latest cursor.
        self.to_unlike = self.gather_posts_to_unlike(**params)
        print(f"Found {len(self.to_unlike)} post{'' if len(self.to_unlike) == 1 else 's'} to unlike.")
        # Only print the cursor suggestion if the stale threshold is not zero.
        if stale_threshold != 0 and hasattr(self, "last_likes_cursor") and self.last_likes_cursor:
            print(f"Suggestion: For future runs, consider using the -c flag with this cursor: {self.last_likes_cursor}")

        # Then, gather posts to delete.
        self.to_delete = self.gather_posts_to_delete(**params)
        print(f"Found {len(self.to_delete)} post{'' if len(self.to_delete) == 1 else 's'} to delete.")

        # Now archive the repository and include the cursor suggestion in the HTML.
        self.archive_repo(**params, cursor_suggestion=(self.last_likes_cursor if hasattr(self, "last_likes_cursor") else ""))

    def unlike(self):
        n_unlike = len(self.to_unlike)
        prompt = None
        while not self.autodelete and prompt not in ("Y", "n"):
            prompt = input(f"\nProceed to unlike {n_unlike} post{'' if n_unlike == 1 else 's'}? WARNING: THIS IS DESTRUCTIVE AND CANNOT BE UNDONE. Y/n: ")
        if self.autodelete or prompt == "Y":
            self.batch_unlike_posts()

    def delete(self):
        n_delete = len(self.to_delete)
        prompt = None
        while not self.autodelete and prompt not in ("Y", "n"):
            prompt = input(f"\nProceed to delete {n_delete} post{'' if n_delete == 1 else 's'}? WARNING: THIS IS DESTRUCTIVE AND CANNOT BE UNDONE. Y/n: ")
        if self.autodelete or prompt == "Y":
            self.batch_delete_posts()

# -------------------------------
# Main Script Execution
# -------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("-u", "--username", help="Bluesky username", required=True)
    parser.add_argument("-p", "--password", help="Bluesky password", required=True)
    parser.add_argument("-l", "--max-reposts", help="""The upper bound of the number of reposts a post can have before it is deleted.
Ignore or set to 0 to not set an upper limit. Defaults to 0.""", default=0, type=int)
    parser.add_argument("-s", "--stale-limit", help="""The age in days after which posts are considered stale and subject to deletion.
Ignore or set to 0 to not set an upper limit. Defaults to 0.""", default=0, type=int)
    parser.add_argument("-d", "--domains-to-protect", help="""A comma separated list of domain names to protect.
Posts linking to these domains will not be auto-deleted regardless of age or virality. Default is empty.""", default="")
    parser.add_argument("-c", "--fixed-likes-cursor", help="""A token to limit the pagination of likes (to avoid fetching the entire history).
Default is empty.""", default="")
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("-v", "--verbose", help="Show more information about what is happening.", action="store_true")
    verbosity.add_argument("-vv", "--very-verbose", help="Show granular information about what is happening.", action="store_true")
    parser.add_argument("-y", "--yes", help="Ignore warning prompts for deletion. Necessary for automation.", action="store_true", default=False)
    args = parser.parse_args()

    creds = Credentials(args.username, args.password)
    verbosity_level = 0
    if args.verbose:
        verbosity_level = 1
    elif args.very_verbose:
        verbosity_level = 2

    params = {
        'viral_threshold': max([0, args.max_reposts]),
        'stale_threshold': max([0, args.stale_limit]),
        'domains_to_protect': [s.strip() for s in args.domains_to_protect.split(",") if s.strip()],
        'fixed_likes_cursor': args.fixed_likes_cursor,
        'verbosity': verbosity_level,
        'autodelete': args.yes
    }

    sd = SkeeterDeleter(credentials=creds, **params)
    sd.unlike()
    sd.delete()
