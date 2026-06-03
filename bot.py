import discord
from discord import app_commands
from discord.ext import commands
import os
import time
import json
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
TIMERS_FILE = "boss_timers.json"

DEFAULT_TIMERS = {
    "hanure":   12 * 3600,
    "morpheus": 8  * 3600,
    "rangora":  8  * 3600,
    "vyrava":   6  * 3600,
    "nazar":    2  * 3600,
}


def load_timers() -> dict:
    if os.path.exists(TIMERS_FILE):
        with open(TIMERS_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_TIMERS.copy()


def save_timers(timers: dict):
    with open(TIMERS_FILE, "w") as f:
        json.dump(timers, f, indent=2)


boss_timers = load_timers()

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


def find_boss(content: str) -> str | None:
    lower = content.strip().lower()
    if lower in boss_timers:
        return lower
    return None


def hours_to_seconds(hours: float) -> int:
    return int(hours * 3600)


def seconds_to_hours(seconds: int) -> float:
    return seconds / 3600


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user} — slash commands synced.")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if message.channel.id != CHANNEL_ID:
        return

    boss = find_boss(message.content)
    if boss is None:
        return

    spawn_unix = int(time.time()) + boss_timers[boss]
    await message.delete()
    await message.channel.send(
        f"**{boss.capitalize()}** spawns <t:{spawn_unix}:R>"
    )


@bot.tree.command(name="addtimer", description="Add a new boss with a respawn timer.")
@app_commands.describe(boss="Boss name", hours="Respawn time in hours (decimals OK, e.g. 1.5)")
async def addtimer(interaction: discord.Interaction, boss: str, hours: float):
    key = boss.lower()
    if key in boss_timers:
        await interaction.response.send_message(
            f"`{key}` already exists. Use `/edittimer` to change it.", ephemeral=True
        )
        return
    boss_timers[key] = hours_to_seconds(hours)
    save_timers(boss_timers)
    await interaction.response.send_message(
        f"Added **{key.capitalize()}** with a {hours}h respawn timer.", ephemeral=True
    )


@bot.tree.command(name="edittimer", description="Edit the respawn timer for an existing boss.")
@app_commands.describe(boss="Boss name", hours="New respawn time in hours (decimals OK, e.g. 1.5)")
async def edittimer(interaction: discord.Interaction, boss: str, hours: float):
    key = boss.lower()
    if key not in boss_timers:
        await interaction.response.send_message(
            f"`{key}` not found. Use `/addtimer` to add it.", ephemeral=True
        )
        return
    old = seconds_to_hours(boss_timers[key])
    boss_timers[key] = hours_to_seconds(hours)
    save_timers(boss_timers)
    await interaction.response.send_message(
        f"Updated **{key.capitalize()}**: {old}h → {hours}h", ephemeral=True
    )


@bot.tree.command(name="removetimer", description="Remove a boss from the timer list.")
@app_commands.describe(boss="Boss name to remove")
async def removetimer(interaction: discord.Interaction, boss: str):
    key = boss.lower()
    if key not in boss_timers:
        await interaction.response.send_message(f"`{key}` not found.", ephemeral=True)
        return
    del boss_timers[key]
    save_timers(boss_timers)
    await interaction.response.send_message(
        f"Removed **{key.capitalize()}** from the timer list.", ephemeral=True
    )


@bot.tree.command(name="listtimers", description="List all bosses and their respawn timers.")
async def listtimers(interaction: discord.Interaction):
    if not boss_timers:
        await interaction.response.send_message("No bosses configured.", ephemeral=True)
        return
    lines = [f"**{k.capitalize()}** — {seconds_to_hours(v)}h" for k, v in boss_timers.items()]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


bot.run(TOKEN)
