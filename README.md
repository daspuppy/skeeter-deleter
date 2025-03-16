# skeeter-deleter
A github action for auto-deleting Bluesky posts.

THIS CODE IS VERY DESTRUCTIVE. The maintainer assumes no liability or warranty for its use. Use at your own peril.

This code was created for my own personal use, and my use alone. I share it here to learn more about how it works, and to document my journey of making it a better script. Other than the original pieces where I forked it from, the whole code is AI generated. I am not a coder!

## What it is

This is a command-line tool that allows a user to download an archive of their Bluesky posts, remove likes, and delete old posts per user-specified criteria, namely age and virality.

### Why delete old posts?

Social media is a great tool to connect people, but it can also be a tool to harass and harm people. One of the more insidious social media behaviors is the tendency to dig up old, out-of-context posts and use them to impugn, impeach, harass, molest, or otherwise defame other users. Similarly, posts that go viral tend to attract unwanted attention, which can lead to arguments, harassment, or other unpleasant experiences.

This tool helps purge your profile so this can't happen, while also preserving a private archive of the posts for any future needs.

### What if I want to keep some posts?

The tool allows you to create a curated feed of your content. Simply "like" your own post and it will be marked for preservation. Beware: if you unlike the post, it may be deleted if you run this script again.

### How does it work?

The tool works as follows:

1. it downloads a CAR archive and embedded media and stores it to an `archive` folder locally
1. it reads your account's likes feed and gathers likes of a certain configurable age
1. it reads your account's posts, replies, and reposts and gathers all such items of a certain configurable age or popularity, as measured by the number of reblogs
1. it unlikes posts
1. it deletes posts

## Installation

Clone this repository and install the python libraries from `requirements.txt` using your preferred python package management solution. Note: you will need to install `libmagic`. Please see the instructions on [the `python-magic` pypi page](https://pypi.org/project/python-magic/).

**You no longer need to set environment variables, `BLUESKY_USERNAME` and `BLUESKY_PASSWORD` in your OS. I suggest creating an App-Password.**

## Running

Here are some **example commands** you might include in your README to show how best to use the script. Each example highlights a different combination of flags and scenarios.

---

## **1. Basic Usage (No Deletions)**

```bash
python skeeter_deleter.py \
  -u myusername \
  -p mypassword
```

- **What it does:**
  - Logs in with the given username / password.
  - Archives your repository (CAR file + media blobs).
  - Gathers likes and posts, but with the default thresholds – i.e., `--max-reposts=0` and `--stale-limit=0`.
  - Because both thresholds are zero, **no** posts or likes are removed (the script effectively doesn’t find any stale/viral posts).
  - Prompts you whether to “unlike” or “delete,” but it’ll find zero items.

---

## **2. Delete Old Posts, No Virality Check**

```bash
python skeeter_deleter.py \
  -u myusername \
  -p mypassword \
  -s 50
```

- **What it does:**
  - Any post older than **50 days** is considered stale.
  - Because `--max-reposts` is left at `0`, we ignore virality.
  - Gathers 100 pages of likes and 100 pages of posts (the default `--pages-per-run=100`) per run, storing its progress in `resume_data.json` so it can resume later if you re-run the script.
  - After gathering, it prompts you to confirm unliking and deleting.

---

## **3. Virality + Old Posts, With Fewer Pages Per Run**

```bash
python skeeter_deleter.py \
  -u myusername \
  -p mypassword \
  -l 20 \
  -s 30 \
  --pages-per-run 50
```

- **What it does:**
  - **–l 20:** any post with 20+ reposts is considered “viral.”
  - **–s 30:** any post older than 30 days is considered stale.
  - **–pages-per-run 50:** the script fetches up to **50 pages** of likes and 50 pages of posts each time you run it, then stops. 
    - Each “page” is up to 100 items. If you have more items than that, you can simply rerun the script – it will pick up where it left off.
  - This partial-run approach is ideal for large accounts, preventing huge single runs.

---

## **4. Automatic Confirm, Verbose Logs**

```bash
python skeeter_deleter.py \
  -u myusername \
  -p mypassword \
  -s 90 \
  -v \
  -y
```

- **What it does:**
  - **–v:** prints verbose logs so you see new cursors, archiving progress, etc.
  - **–y:** automatically says “Yes” to destructive actions (unliking and deleting). You won’t be prompted for confirmation, so be sure you really want this.
  - **–s 90:** anything older than 90 days is stale. Defaults for the rest (like viral threshold = 0, pages-per-run = 100).

---

## **5. Skipping Old Likes with a Fixed Cursor**

```bash
python skeeter_deleter.py \
  -u myusername \
  -p mypassword \
  -s 365 \
  -c 3lx7abcxyz2
```

- **What it does:**
  - **–c 3lx7abcxyz2:** If you already cleared older likes, and you have a known “cursor” from a previous run, the script won’t re-fetch pages older than that cursor. This can speed things up significantly.
  - **–s 365:** anything older than one year is stale.
  - Keeps using default pages-per-run = 100.
 
## **6. Skip Reposts (normal usage)**

```python skeeter_deleter.py -u user -p pass -l 20 -s 50 -b 0```

Leaves reposts alone, only deletes normal posts older than 50 days or above 20 reposts.

## **7. Undo Reposts Older Than 7 Days**

```python skeeter_deleter.py \
  -u user \
  -p pass \
  -l 10 \
  -s 30 \
  -b 7 \
  --pages-per-run 50 \
  -v
```

Normal posts older than 30 days or with 10+ reposts are removed.
Reposts older than 7 days are undone.
Each partial run processes up to 50 pages at a time.
Prints verbose logs.

## **8. Just Reposts**

```python skeeter_deleter.py \
  -u user \
  -p pass \
  -s 0 \
  -l 0 \
  -b 14 \
  -y
```

Ignores normal posts entirely (stale-limit=0, max-reposts=0 means skip).
–b 14: Undoes reposts older than 14 days.
Automatically says “yes” to destructive actions.

---

## **Tips & Reminders**

- **resume_data.json**  
  - The script saves your progress (the “last_likes_cursor” and “last_posts_cursor”) in `resume_data.json`. If you crash or exit, a subsequent run will resume from that file unless you override it via **-c**.

- **Exponential Backoff**  
  - If the server returns 502 (or other network errors), it retries automatically up to three times before failing.

- **Rate Limiting**  
  - We use a **750ms delay** on every request to help avoid Bluesky’s rate limits. If you see many 429 or 502 errors, you may still need to slow down further or break your runs into smaller sessions.

- **Partial Runs**  
  - With **–pages-per-run**, you can keep each session at a manageable size. If your account is large, you can repeatedly run the script. It always picks up from the last saved cursor.

- **Automation**  
  - You can wrap the script in a simple Bash loop to auto-restart on crash, or use a more advanced approach to increment pages-per-run if you’re not seeing progress.  

All these examples demonstrate how to tune the script to handle your account size, your definition of “old,” and how many pages to process per run. Feel free to customize the approach to match your needs!

### Automating

This could be run in a docker container in a Github action, in a cloud function, or in any other scheduled environment. IF it doesn't crash!

A simple shell script could look like this:

    source /path/to/skeeter-venv/bin/activate
    python /path/to/skeeter-deleter/skeeter-deleter.py -u username -p mypassword -d example.com,mydomain.net -l 20 -s 14 --pages-per-run 2000 2>&1

## Future Roadmap

- Bug fixing as they come up using it.
- Stop it from crashing for the first (few) runs, and/or catch it crashing to either start again, or pick up where it left off. If the protocoll, or the script allows.
