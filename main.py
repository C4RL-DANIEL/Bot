# full_merged_bot.py

import discord

from discord.ext import commands, tasks

from discord import ui, ButtonStyle

from flask import Flask

import os, sys, threading, asyncio, json, aiohttp

from datetime import datetime

import pytz

import time

# ----------------- CONFIG / FILES -----------------

def read_file(path):

    try:

        with open(path, "r") as f:

            return f.read().strip()

    except:

        return None

TOKEN = read_file("token.txt")

LOG_CHANNEL_ID = int(read_file("channel_id.txt") or 0)

REPLIT_URL = read_file("site.txt") or "http://localhost:8080"

OWNER_ID = 1156569457125244949

CONFIG_FILE = "config.json"

WELCOME_FILE = "welcome_config.json"

# defaults

DEFAULT_CONFIG = {

    "restart_interval": 1800,

    "allowed_roles": ["Staff", "Admin", "Moderator"],

    "shutdown_default_minutes": 5

}

DEFAULT_WELCOME = {

    "welcome_enabled": True,

    "goodbye_enabled": True,

    "welcome_channel_id": None,

    "welcome_message": "🎉 Welcome {user} to {guild}!",

    "goodbye_message": "👋 Goodbye {user}, we’ll miss you in {guild}!"

}

# Load/save helpers

def load_json(path, default):

    try:

        with open(path, "r") as f:

            return json.load(f)

    except:

        with open(path, "w") as f:

            json.dump(default, f, indent=4)

        return default.copy()

def save_json(path, data):

    with open(path, "w") as f:

        json.dump(data, f, indent=4)

config = load_json(CONFIG_FILE, DEFAULT_CONFIG)

welcome_cfg = load_json(WELCOME_FILE, DEFAULT_WELCOME)

# convenience vars

restart_interval = config.get("restart_interval", 1800)

ALLOWED_ROLES = config.get("allowed_roles", DEFAULT_CONFIG["allowed_roles"])

shutdown_default_minutes = config.get("shutdown_default_minutes", DEFAULT_CONFIG["shutdown_default_minutes"])

# ----------------- FLASK KEEP-ALIVE -----------------

app = Flask(__name__)

@app.route('/')

def home():

    return "Bot is alive!"

def run_flask():

    app.run(host='0.0.0.0', port=8080)

def keep_alive():

    t = threading.Thread(target=run_flask, daemon=True)

    t.start()

# ----------------- TIME UTIL -----------------

PH_TZ = pytz.timezone("Asia/Manila")

def ph_time_now():

    return datetime.now(PH_TZ).strftime("%Y-%m-%d %H:%M:%S")

# ----------------- DISCORD SETUP -----------------

intents = discord.Intents.default()

intents.guilds = True

intents.members = True

intents.messages = True

intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

last_self_ping = None

last_restart_time = None

restart_timer = None

# ----------------- LOGGING -----------------

async def send_log(message: str, action: str = "INFO"):

    if not LOG_CHANNEL_ID:

        return

    ch = bot.get_channel(LOG_CHANNEL_ID)

    if not ch:

        return

    colors = {"INFO":0x2ecc71, "COMMAND":0x3498db, "ERROR":0xe74c3c, "RESTART":0xf1c40f, "ROLE":0x9b59b6}

    emojis = {"INFO":"ℹ️","COMMAND":"📝","ERROR":"❌","RESTART":"♻️","ROLE":"🎭"}

    color = colors.get(action, 0x2ecc71)

    emoji = emojis.get(action, "ℹ️")

    embed = discord.Embed(title=f"{emoji} {action} Log",

                          description=message,

                          color=color,

                          timestamp=datetime.now(PH_TZ))

    embed.set_footer(text=f"Logged at {ph_time_now()} (PH Time)")

    try:

        await ch.send(embed=embed)

    except:

        # fallback to plain message if embed send fails

        try:

            await ch.send(f"{emoji} {action} Log — {message}")

        except:

            pass

# ----------------- AUTO-RESTART -----------------

def restart_process():

    # note: this re-executes the python process (works on most hosts)

    os.execv(sys.executable, [sys.executable] + sys.argv)

def schedule_restart():

    global restart_timer

    if restart_timer:

        restart_timer.cancel()

    restart_timer = threading.Timer(restart_interval, restart_process)

    restart_timer.start()

schedule_restart()

# ----------------- SELF-PING -----------------

@tasks.loop(minutes=1)

async def self_ping_task():

    global last_self_ping

    ts = ph_time_now()

    try:

        async with aiohttp.ClientSession() as session:

            async with session.get(REPLIT_URL) as resp:

                await resp.text()

        last_self_ping = ts

        await send_log(f"✅ Self-ping successful at {ts}", action="INFO")

    except Exception as e:

        await send_log(f"❌ Self-ping failed at {ts}: {e}", action="ERROR")

# ----------------- PERMISSION HELPERS -----------------

def is_staff_check():

    async def predicate(ctx):

        if ctx.author.id == OWNER_ID:

            return True

        # guild permission

        if ctx.author.guild_permissions.manage_guild:

            return True

        for role in ctx.author.roles:

            if role.name in ALLOWED_ROLES:

                return True

        return False

    return commands.check(predicate)

# ----------------- AUTO-DELETE (after invoke) -----------------

@bot.after_invoke

async def _delete_command_message(ctx):

    try:

        if ctx.message:

            await ctx.message.delete()

    except:

        pass

# also delete any message starting with "!" (non-command fallback)

@bot.event

async def on_message(message):

    if message.author.bot:

        return

    # immediate delete for raw '!' messages (skip if it's a bot DM)

    if message.content.startswith("!"):

        try:

            await message.delete()

        except:

            pass

    # CODE listener (we also keep code detection here)

    content_up = message.content.upper()

    if content_up.startswith("CODE "):

        # handle CODE system

        parts = message.content.split(":", 1)

        code_part = parts[0].strip().replace("CODE ", "").upper()

        note = parts[1].strip() if len(parts) > 1 else None

        if code_part in CODE_MEANINGS:

            # check permission: manage_messages or allowed role

            has_perm = message.author.guild_permissions.manage_messages

            for r in message.author.roles:

                if r.name in ALLOWED_ROLES:

                    has_perm = True

                    break

            if not has_perm:

                try:

                    await message.channel.send("❌ You do not have permission to use CODE commands.", delete_after=10)

                except:

                    pass

            else:

                meaning, color, emoji = CODE_MEANINGS[code_part]

                embed = discord.Embed(title=f"{emoji} CODE {code_part}", description=meaning, color=color)

                if note:

                    words = note.split()

                    formatted = [f"**{w[1:]}**" if w.startswith(":") else w for w in words]

                    embed.add_field(name="📝 Note", value=" ".join(formatted), inline=False)

                try:

                    await message.delete()

                except:

                    pass

                if message.reference and message.reference.resolved:

                    try:

                        await message.reference.resolved.reply(embed=embed)

                    except:

                        await message.channel.send(embed=embed)

                else:

                    await message.channel.send(embed=embed)

    # allow commands to be processed

    await bot.process_commands(message)

# ----------------- CODE SYSTEM DATA -----------------

CODE_MEANINGS = {

    "BLUE": ("MAY VERIFICATION", 0x3498db, "🔹"),

    "RED": ("PALDO", 0xe74c3c, "🔴"),

    "GREEN": ("NA LOOT NA", 0x2ecc71, "🟢"),

    "YELLOW": ("MAY PAG ASA PA", 0xf1c40f, "🟡"),

    "ORANGE": ("NABUKSAN", 0xe67e22, "🟠"),

    "PURPLE": ("SECURE", 0x9b59b6, "🟣"),

    "BLACK": ("BAN", 0x000000, "⚫")

}

# ----------------- BASIC PUBLIC COMMANDS -----------------

@bot.command(name="status")

async def status_cmd(ctx):

    e = discord.Embed(title="📊 Bot Status", color=0x00ffcc)

    e.add_field(name="Bot Online", value="✅ Yes", inline=False)

    e.add_field(name="Servers", value=str(len(bot.guilds)), inline=True)

    e.add_field(name="Last Self-Ping", value=(last_self_ping or "Never"), inline=True)

    await ctx.send(embed=e, delete_after=20)

@bot.command(name="publicstatus")

async def publicstatus_cmd(ctx):

    mins = restart_interval // 60

    lr = last_restart_time or "No restart recorded yet"

    e = discord.Embed(title="📊 Public Status", color=0x3498db)

    e.add_field(name="Auto-Restart Interval", value=f"{mins} minutes", inline=False)

    e.add_field(name="Last Restart", value=lr, inline=False)

    await ctx.send(embed=e)

    await send_log(f"[{ph_time_now()}] {ctx.author} ran !publicstatus", action="COMMAND")

@bot.command(name="config")

async def config_cmd(ctx):

    mins = restart_interval // 60

    roles = ", ".join(ALLOWED_ROLES) if ALLOWED_ROLES else "None"

    e = discord.Embed(title="⚙️ Bot Configuration", color=0x00ffcc)

    e.add_field(name="Restart Interval", value=f"{mins} minutes", inline=False)

    e.add_field(name="Allowed Roles", value=roles, inline=False)

    await ctx.send(embed=e)

    await send_log(f"[{ph_time_now()}] {ctx.author} ran !config", action="COMMAND")

# custom help

@bot.command(name="help")

async def help_cmd(ctx):

    e = discord.Embed(title="📖 Help", color=0x00ffcc)

    e.add_field(name="Public", value="`!status`, `!publicstatus`, `!config`, `!help`, `!notifier`, `!welcomemenu`", inline=False)

    e.set_footer(text="Staff commands: use !staffhelp")

    await ctx.send(embed=e)

@bot.command(name="notifier")

async def notifier_cmd(ctx):

    e = discord.Embed(title="📖 CODE Help", description="Available CODE alerts:", color=0x00ffcc)

    for code, (meaning, _, emoji) in CODE_MEANINGS.items():

        e.add_field(name=f"{emoji} CODE {code}", value=meaning, inline=False)

    e.set_footer(text="Usage: CODE <COLOR> : optional note")

    await ctx.send(embed=e, delete_after=20)

# ----------------- STAFF COMMANDS (full) -----------------

@bot.command(name="staffhelp", hidden=True)

@is_staff_check()

async def staffhelp_cmd(ctx):

    e = discord.Embed(title="🛠️ Staff Help", color=0xffcc00)

    staff_cmds = {

        "restart": "Manual restart (30s cooldown)",

        "lastrestart": "Show last restart",

        "setrestarttime <min>": "Set auto-restart interval (5-720)",

        "showrestarttime": "Show current interval",

        "addrole <role>": "Add allowed staff role (name or mention)",

        "removerole <role>": "Remove allowed staff role (name or mention)",

        "listroles": "List allowed staff roles",

        "cheatsheet": "Quick reference",

        "welcomemenu": "Interactive welcome & goodbye menu",

        "shutdown <minutes?>": "Owner-only timed shutdown"

    }

    e.add_field(name="Staff Commands", value="\n".join([f"!{k} → {v}" for k,v in staff_cmds.items()]), inline=False)

    await ctx.send(embed=e, delete_after=25)

    await send_log(f"[{ph_time_now()}] {ctx.author} ran !staffhelp", action="COMMAND")

@bot.command(name="cheatsheet", hidden=True)

@is_staff_check()

async def cheatsheet_cmd(ctx):

    e = discord.Embed(title="📖 Cheatsheet", color=0x7289da)

    e.add_field(name="Commands", value="See !staffhelp for list", inline=False)

    await ctx.send(embed=e, delete_after=20)

    await send_log(f"[{ph_time_now()}] {ctx.author} ran !cheatsheet", action="COMMAND")

# restart

@bot.command(name="restart", hidden=True)

@is_staff_check()

@commands.cooldown(1, 30, commands.BucketType.user)

async def restart_cmd(ctx):

    global last_restart_time

    last_restart_time = ph_time_now()

    await ctx.send("♻️ Restarting bot...", delete_after=10)

    await send_log(f"♻️ Bot restart requested by {ctx.author}", action="RESTART")

    await bot.close()

    # ensure process restarts

    restart_process()

@bot.command(name="lastrestart", hidden=True)

@is_staff_check()

@commands.cooldown(1, 30, commands.BucketType.user)

async def lastrestart_cmd(ctx):

    if last_restart_time:

        await ctx.send(f"♻️ Last restart: **{last_restart_time}**", delete_after=15)

    else:

        await ctx.send("❌ No restart recorded yet.", delete_after=10)

    await send_log(f"[{ph_time_now()}] {ctx.author} ran !lastrestart", action="COMMAND")

@bot.command(name="setrestarttime", hidden=True)

@is_staff_check()

async def setrestarttime_cmd(ctx, minutes: int):

    global restart_interval

    if minutes < 5 or minutes > 720:

        await ctx.send("❌ Value must be between 5 and 720 minutes.", delete_after=10)

        return

    restart_interval = minutes * 60

    config["restart_interval"] = restart_interval

    save_json(CONFIG_FILE, config)

    schedule_restart()

    await ctx.send(f"✅ Auto-restart interval set to {minutes} minutes.", delete_after=10)

    await send_log(f"⚙️ Restart interval changed to {minutes}m by {ctx.author}", action="ROLE")

@bot.command(name="showrestarttime", hidden=True)

@is_staff_check()

async def showrestarttime_cmd(ctx):

    await ctx.send(f"⏱️ Current auto-restart interval: **{restart_interval//60} minutes**", delete_after=10)

    await send_log(f"[{ph_time_now()}] {ctx.author} ran !showrestarttime", action="COMMAND")

# addrole / removerole accept mention or name

@bot.command(name="addrole", hidden=True)

@is_staff_check()

async def addrole_cmd(ctx, *, role_input: str):

    # try mention -> get role by id, else by name (case-insensitive)

    guild = ctx.guild

    role = None

    # role mention or id

    if ctx.message.role_mentions:

        role = ctx.message.role_mentions[0]

    else:

        # try to parse as id

        if role_input.isdigit():

            role = guild.get_role(int(role_input))

        else:

            # find by name case-insensitive

            for r in guild.roles:

                if r.name.lower() == role_input.lower():

                    role = r

                    break

    if not role:

        await ctx.send("❌ Role not found. Use role mention, id, or exact name.", delete_after=10)

        return

    if role.name in ALLOWED_ROLES:

        await ctx.send(f"❌ Role `{role.name}` already allowed.", delete_after=10)

        return

    ALLOWED_ROLES.append(role.name)

    config["allowed_roles"] = ALLOWED_ROLES

    save_json(CONFIG_FILE, config)

    await ctx.send(f"✅ Role `{role.name}` added to allowed roles.", delete_after=10)

    await send_log(f"⚙️ {ctx.author} added role `{role.name}` to allowed roles.", action="ROLE")

@bot.command(name="removerole", hidden=True)

@is_staff_check()

async def removerole_cmd(ctx, *, role_input: str):

    guild = ctx.guild

    role = None

    if ctx.message.role_mentions:

        role = ctx.message.role_mentions[0]

    else:

        if role_input.isdigit():

            role = guild.get_role(int(role_input))

        else:

            for r in guild.roles:

                if r.name.lower() == role_input.lower():

                    role = r

                    break

    if not role or role.name not in ALLOWED_ROLES:

        await ctx.send("❌ Role not in allowed list.", delete_after=10)

        return

    ALLOWED_ROLES.remove(role.name)

    config["allowed_roles"] = ALLOWED_ROLES

    save_json(CONFIG_FILE, config)

    await ctx.send(f"✅ Role `{role.name}` removed from allowed roles.", delete_after=10)

    await send_log(f"⚙️ {ctx.author} removed role `{role.name}` from allowed roles.", action="ROLE")

@bot.command(name="listroles", hidden=True)

@is_staff_check()

async def listroles_cmd(ctx):

    await ctx.send(f"📋 Allowed roles: **{', '.join(ALLOWED_ROLES) if ALLOWED_ROLES else 'None'}**", delete_after=15)

    await send_log(f"[{ph_time_now()}] {ctx.author} ran !listroles", action="COMMAND")

# ----------------- SHUTDOWN (owner only, timed restart) -----------------

@bot.command(name="shutdown", hidden=True)

async def shutdown_cmd(ctx, minutes: int = None):

    # owner-only

    if ctx.author.id != OWNER_ID:

        return await ctx.send("❌ Only the bot owner can use this command.", delete_after=10)

    minutes = minutes if (minutes is not None) else config.get("shutdown_default_minutes", shutdown_default_minutes)

    if minutes < 0:

        minutes = 0

    await ctx.send(f"🛑 Shutting down. Bot will attempt to restart in {minutes} minute(s).", delete_after=10)

    await send_log(f"🛑 Shutdown initiated by {ctx.author} — restart in {minutes}m", action="RESTART")

    # schedule restart (re-exec) after minutes; then close bot

    def delayed_restart(t):

        time.sleep(t*60)

        try:

            restart_process()

        except Exception:

            os.execv(sys.executable, [sys.executable] + sys.argv)

    threading.Thread(target=delayed_restart, args=(minutes,), daemon=True).start()

    await bot.close()

@bot.command(name="setshutdowntime", hidden=True)

@is_staff_check()

async def setshutdowntime_cmd(ctx, minutes: int):

    config["shutdown_default_minutes"] = max(0, minutes)

    save_json(CONFIG_FILE, config)

    await ctx.send(f"✅ Default shutdown time set to {minutes} minute(s).", delete_after=10)

    await send_log(f"⚙️ {ctx.author} set default shutdown time to {minutes}m", action="ROLE")
    
    

# ----------------- WELCOME / GOODBYE (interactive buttons + fallback commands) -----------------

class WelcomeView(ui.View):

    def __init__(self, author):

        super().__init__(timeout=300)

        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:

        if interaction.user.id != self.author.id:

            await interaction.response.send_message("❌ Only the command author can use this menu.", ephemeral=True)

            return False

        return True

    @ui.button(label="Set Welcome Message", style=ButtonStyle.primary)

    async def btn_set_welcome(self, interaction: discord.Interaction, button: ui.Button):

        await interaction.response.send_message("✍️ Type the new welcome message in chat (use {user} and {guild}):", ephemeral=True)

        try:

            msg = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id and m.channel == interaction.channel, timeout=60)

            welcome_cfg["welcome_message"] = msg.content

            save_json(WELCOME_FILE, welcome_cfg)

            try: await msg.delete()

            except: pass

            await interaction.followup.send("✅ Welcome message updated.", ephemeral=True)

            await send_log(f"⚙️ {interaction.user} set welcome message", action="COMMAND")

        except asyncio.TimeoutError:

            await interaction.followup.send("⏳ Timeout. Please try again.", ephemeral=True)

    @ui.button(label="Set Goodbye Message", style=ButtonStyle.danger)

    async def btn_set_goodbye(self, interaction: discord.Interaction, button: ui.Button):

        await interaction.response.send_message("✍️ Type the new goodbye message in chat (use {user} and {guild}):", ephemeral=True)

        try:

            msg = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id and m.channel == interaction.channel, timeout=60)

            welcome_cfg["goodbye_message"] = msg.content

            save_json(WELCOME_FILE, welcome_cfg)

            try: await msg.delete()

            except: pass

            await interaction.followup.send("✅ Goodbye message updated.", ephemeral=True)

            await send_log(f"⚙️ {interaction.user} set goodbye message", action="COMMAND")

        except asyncio.TimeoutError:

            await interaction.followup.send("⏳ Timeout. Please try again.", ephemeral=True)

    @ui.button(label="Set Welcome Channel (current)", style=ButtonStyle.secondary)

    async def btn_set_channel(self, interaction: discord.Interaction, button: ui.Button):

        # set the channel where button was clicked

        cid = interaction.channel.id

        welcome_cfg["welcome_channel_id"] = cid

        save_json(WELCOME_FILE, welcome_cfg)

        await interaction.response.send_message(f"✅ Welcome/goodbye channel set to {interaction.channel.mention}", ephemeral=True)

        await send_log(f"⚙️ {interaction.user} set welcome/goodbye channel to {interaction.channel}", action="COMMAND")

    @ui.button(label="Preview Messages", style=ButtonStyle.success)

    async def btn_preview(self, interaction: discord.Interaction, button: ui.Button):

        welcome_text = welcome_cfg.get("welcome_message", DEFAULT_WELCOME["welcome_message"])

        goodbye_text = welcome_cfg.get("goodbye_message", DEFAULT_WELCOME["goodbye_message"])

        e = discord.Embed(title="👋 Preview", color=0x95a5a6)

        e.add_field(name="Welcome", value=welcome_text.format(user=interaction.user.mention, guild=interaction.guild.name), inline=False)

        e.add_field(name="Goodbye", value=goodbye_text.format(user=interaction.user.mention, guild=interaction.guild.name), inline=False)

        await interaction.response.send_message(embed=e, ephemeral=True)

    @ui.button(label="Toggle Welcome/Goodbye", style=ButtonStyle.secondary)

    async def btn_toggle(self, interaction: discord.Interaction, button: ui.Button):

        welcome_cfg["welcome_enabled"] = not welcome_cfg.get("welcome_enabled", True)

        welcome_cfg["goodbye_enabled"] = not welcome_cfg.get("goodbye_enabled", True)

        save_json(WELCOME_FILE, welcome_cfg)

        state = "ON" if welcome_cfg["welcome_enabled"] else "OFF"

        await interaction.response.send_message(f"🔄 Welcome/Goodbye toggled **{state}**.", ephemeral=True)

        await send_log(f"⚙️ {interaction.user} toggled welcome/goodbye to {state}", action="COMMAND")

    @ui.button(label="Reset to Default", style=ButtonStyle.danger)

    async def btn_reset(self, interaction: discord.Interaction, button: ui.Button):

        for k, v in DEFAULT_WELCOME.items():

            welcome_cfg[k] = v

        save_json(WELCOME_FILE, welcome_cfg)

        await interaction.response.send_message("♻️ Welcome/goodbye settings reset to default.", ephemeral=True)

        await send_log(f"⚙️ {interaction.user} reset welcome/goodbye settings", action="COMMAND")

# Command to open menu

@bot.command(name="welcomemenu")

@is_staff_check()

async def welcomemenu_cmd(ctx):

    view = WelcomeView(ctx.author)

    e = discord.Embed(title="👋 Welcome & Goodbye Menu", description="Use the buttons below to configure settings.", color=0x1abc9c)

    e.add_field(name="Current Welcome", value=welcome_cfg.get("welcome_message", DEFAULT_WELCOME["welcome_message"]), inline=False)

    e.add_field(name="Current Goodbye", value=welcome_cfg.get("goodbye_message", DEFAULT_WELCOME["goodbye_message"]), inline=False)

    channel_id = welcome_cfg.get("welcome_channel_id")

    channel_display = f"<#{channel_id}>" if channel_id else "Not Set"

    e.add_field(name="Channel", value=channel_display, inline=False)

    e.add_field(name="Enabled", value=f"Welcome: {welcome_cfg.get('welcome_enabled', True)} | Goodbye: {welcome_cfg.get('goodbye_enabled', True)}", inline=False)

    await ctx.send(embed=e, view=view, delete_after=300)

# Events for actual welcome/goodbye

@bot.event

async def on_member_join(member):

    if welcome_cfg.get("welcome_enabled", True) and welcome_cfg.get("welcome_channel_id"):

        ch = member.guild.get_channel(welcome_cfg["welcome_channel_id"])

        if ch:

            try:

                msg = welcome_cfg.get("welcome_message", DEFAULT_WELCOME["welcome_message"])

                await ch.send(msg.format(user=member.mention, guild=member.guild.name))

            except:

                pass

@bot.event

async def on_member_remove(member):

    if welcome_cfg.get("goodbye_enabled", True) and welcome_cfg.get("welcome_channel_id"):

        ch = member.guild.get_channel(welcome_cfg["welcome_channel_id"])

        if ch:

            try:

                msg = welcome_cfg.get("goodbye_message", DEFAULT_WELCOME["goodbye_message"])

                await ch.send(msg.format(user=member.mention, guild=member.guild.name))

            except:

                pass

# ----------------- BOT START -----------------

@bot.event

async def on_ready():

    await send_log(f"✅ Bot is online as {bot.user}", action="INFO")

    self_ping_task.start()

    keep_alive()

    print(f"Bot online as {bot.user}")

if TOKEN:

    bot.run(TOKEN)

else:

    print("❌ No token found in token.txt") 