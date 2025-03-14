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

Activate your environment.

Run the command with

```sh
python skeeter-deleter.py
```

with the following command line options:

- `-u [username]`: your Bluesky username

- `-p [password]`: your Bluesky password. I suggest creating an App password for this!

- `-l`, `--max-reposts`: the upper limit of reposts a post can have before it is deleted. This is to prevent post virality by deleting posts once they've grown too popular. Set this to 0 or ignore the flag if you don't want to use this feature. Note: at least either `-s` or `-l` (or both) must be set to delete posts, replies, reblogs, or likes.

- `-s`, `--stale-limit`: the upper limit of the age in days a post can be. This is to prevent people digging up old posts. Set this to 0 or ignore the flag if you don't want to use this feature. Note: at least either `-s` or `-l` (or both) must be set to delete posts, replies, reblogs, or likes.

- `-d`, `--domains-to-protect`: a comma-separated list of domain names to preserve, for example you can configure the tool to not delete links to your blog or your favorite sites. Optional.

- `-c`, `--fixed-likes-cursor`: the cursor ID for the maximum lookback for likes. Due to the ATProto design, fetching likes can take a long time, as the cursor still pages even if there are no old likes to be found. If you have run this tool at least once before, it is recommended to set this to a cursor in the recent past. This can be obtained by running `-v` or `-vv` and copying the cursor output

- `-v`, `--verbose`: emit more information about progress, useful for initial runs where many posts will be archived and deleted

- `-vv`, `--very-verbose`: emit granular information about each post. Not recommended.

- `-y`, `--yes`: automatically answer yes to all warnings about deleting posts, necessary for use in automation.

## Example
`python skeeter_deleter.py -u myusername -p mypassword -d example.com,mydomain.net -l 20 -s 14 -c 222lncibbzz22`

This command:
 - Uses myusername and mypassword for login.
 - Protects posts linking to example.com and mydomain.net.
 - Marks posts with 20 or more reposts as viral and deletes them if not liked by yourself.
 - Treats posts older than 14 days as stale and deletes them if not liked by yourself.
 - Uses 222lncibbzz22 as the fixed likes cursor. Indexing all likes is still extremely slow.
 - Try with `-v` to see that it is actually running. It takes hours. Especially for the first run!
 - use `-y` once you're satisfied with your settings and it will automatically answer yes to all questions about unliking and deleting old posts and reposts you haven't liked yourself.

### Short comings

In all my tests of both the original script and this one, for to me unknown reasons **the script crashes at least once** if not more. *But with every subsequent run it gets further.* Unfortunately it takes the same time it took until it crashed (sometimes hours) plus the then additional time for running further. It has something to do with the likes cursor. That's a part of the script I don't understand at all, let alone that I know how to maybe optimize.

I also needed to add an API call delay of 750 milliseconds. Because once the script has run through the likes cursors successfully, it hits the rate limit of 5000 API calls per hour. With this delay it should not go over 4800 API calls per hour when unliking and deleting old posts. That alone has cost me literal hours to test again and again.

### Automating

This could be run in a docker container in a Github action, in a cloud function, or in any other scheduled environment. IF it doesn't crash!

A simple shell script could look like this:

    source /path/to/skeeter-venv/bin/activate
    python /path/to/skeeter-deleter/skeeter-deleter.py -u username -p mypassword -d example.com,mydomain.net -l 20 -s 14 2>&1

## Future Roadmap

- Bug fixing as they come up using it.
- Stop it from crashing for the first (few) runs, and/or catch it crashing to either start again, or pick up where it left off. If the protocoll, or the script allows.
