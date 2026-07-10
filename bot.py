import os
import sqlite3
import discord
from dotenv import load_dotenv
from discord.ext import commands
from discord import app_commands

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Initialize bot with default intents
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Connect to a local file (creates it if it doesn't exist)
conn = sqlite3.connect('trading_journal.db')
cursor = conn.cursor()

@bot.event
async def on_ready():
    # Create the trades table with all columns
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            trader_name TEXT,
            ticker TEXT,
            direction TEXT,
            entry_price REAL,  -- Added missing column
            closed_price REAL, -- Added missing column
            pnl REAL,
            setup TEXT,
            image_url TEXT,
            notes TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()

    print(f'Logged in as {bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)


# ==========================================
# COMMAND 1: /log
# ==========================================
@bot.tree.command(name="log", description="Log a completed trade to your journal.")
@app_commands.describe(
    ticker="The asset you traded (e.g., AAPL, ES, BTC)",
    direction="Did you go Long or Short?",
    entry_price="The price you entered the trade at",
    closed_price="The price you closed the trade at",
    pnl="Net profit or loss (use negative for loss)",
    setup="The setup or strategy used",
    image="Chart screenshot (optional)",
    notes="Any reflections on the trade (optional)"
)
@app_commands.choices(
    direction=[
        app_commands.Choice(name="Long", value="Long"),
        app_commands.Choice(name="Short", value="Short")
    ]
)
async def log_trade(
    interaction: discord.Interaction, 
    ticker: str, 
    direction: app_commands.Choice[str], 
    entry_price: float,
    closed_price: float,
    pnl: float, 
    setup: str, 
    image: discord.Attachment = None, 
    notes: str = None
):
    
    ticker = ticker.upper()

    # 1. Database Logic
    user_id = interaction.user.id
    trader_name = interaction.user.display_name
    image_url = image.url if image else None
    
    # Save the actual trade data into the database
    cursor.execute('''
        INSERT INTO trades (user_id, trader_name, ticker, direction, entry_price, closed_price, pnl, setup, image_url, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, trader_name, ticker, direction.value, entry_price, closed_price, pnl, setup, image_url, notes))
    
    # Grab the ID IMMEDIATELY after execute, BEFORE commit (fixes the #0 bug)
    trade_id = cursor.lastrowid
    conn.commit()

    # 2. Embed Logic
    embed_color = discord.Color.green() if pnl >= 0 else discord.Color.red()
    embed = discord.Embed(
        title=f"Trade Logged: {ticker.upper()}", 
        color=embed_color,
        timestamp=interaction.created_at
    )

    # Format PnL string with explicit + or - sign
    pnl_string = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
    
    # Adding all fields to the embed
    embed.add_field(name="Direction", value=direction.name, inline=True)
    embed.add_field(name="Setup", value=setup, inline=True)
    embed.add_field(name="PnL", value=pnl_string, inline=True)
    embed.add_field(name="Entry Price", value=f"${entry_price:,.2f}", inline=True)
    embed.add_field(name="Closed Price", value=f"${closed_price:,.2f}", inline=True)
    
    if notes:
        embed.add_field(name="Notes", value=notes, inline=False)
        
    if image:
        embed.set_image(url=image_url)
        
    embed.set_footer(text=f"Trader: {trader_name} | Trade ID: #{trade_id}")
    await interaction.response.send_message(embed=embed)


# ==========================================
# COMMAND 2: /stats
# This must be a completely separate stack
# ==========================================
@bot.tree.command(name="stats", description="Calculate win rate and total PnL.")
@app_commands.describe(target_user="View stats for a specific user (optional)")
async def stats(interaction: discord.Interaction, target_user: discord.Member = None):
    user = target_user or interaction.user
    
    cursor.execute('SELECT pnl FROM trades WHERE user_id = ?', (user.id,))
    trades = cursor.fetchall()
    
    if not trades:
        await interaction.response.send_message(f"{user.display_name} hasn't logged any trades yet.", ephemeral=True)
        return

    total_trades = len(trades)
    winning_trades = sum(1 for trade in trades if trade[0] > 0) 
    
    win_rate = (winning_trades / total_trades) * 100
    total_pnl = sum(trade[0] for trade in trades)
    avg_return = total_pnl / total_trades
    
    embed_color = discord.Color.green() if total_pnl >= 0 else discord.Color.red()
    embed = discord.Embed(
        title=f"Trading Stats: {user.display_name}", 
        color=embed_color
    )
    
    pnl_string = f"+${total_pnl:,.2f}" if total_pnl >= 0 else f"-${abs(total_pnl):,.2f}"
    avg_string = f"+${avg_return:,.2f}" if avg_return >= 0 else f"-${abs(avg_return):,.2f}"
    
    embed.add_field(name="Total PnL", value=pnl_string, inline=False)
    embed.add_field(name="Win Rate", value=f"{win_rate:.1f}%", inline=True)
    embed.add_field(name="Total Trades", value=str(total_trades), inline=True)
    embed.add_field(name="Avg Return/Trade", value=avg_string, inline=True)
    
    await interaction.response.send_message(embed=embed)

# ==========================================
# COMMAND 3: /del
# ==========================================
@bot.tree.command(name="del", description="Delete a logged trade if you made a mistake.")
@app_commands.describe(trade_id="The ID number of the trade (found in the embed footer)")
async def del_trade(interaction: discord.Interaction, trade_id: int):
    user_id = interaction.user.id
    
    # 1. Check if the trade exists AND belongs to the user who typed the command
    cursor.execute('SELECT ticker, pnl FROM trades WHERE trade_id = ? AND user_id = ?', (trade_id, user_id))
    trade = cursor.fetchone()
    
    # If fetchone() returns None, the trade either doesn't exist or isn't theirs
    if not trade:
        await interaction.response.send_message(
            f"❌ Could not find Trade #{trade_id}. It might have already been deleted, or it belongs to another user.", 
            ephemeral=True
        )
        return
        
    # Extract the data so we can tell them exactly what was deleted
    ticker, pnl = trade
    
    # 2. Delete the trade from the database
    cursor.execute('DELETE FROM trades WHERE trade_id = ? AND user_id = ?', (trade_id, user_id))
    conn.commit()
    
    # 3. Send a confirmation message
    # Format the PnL nicely for the confirmation message
    pnl_string = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
    
    await interaction.response.send_message(
        f"Successfully deleted Trade #{trade_id} ({ticker} : {pnl_string}).", 
        # ephemeral=True
    )

# Run the bot
bot.run(TOKEN)