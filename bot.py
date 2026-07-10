import os
import discord
import psycopg2  # Swapped from sqlite3
from dotenv import load_dotenv
from discord.ext import commands
from discord import app_commands
from aiohttp import web  # For the Render keep-alive server

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

# Connect to Supabase Postgres Database
conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

# Initialize bot with default intents
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ==========================================
# WEB SERVER LOGIC (RENDER KEEP-ALIVE)
# ==========================================
async def handle_ping(request):
    return web.Response(text="Bot is awake and running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Render automatically assigns a PORT env variable. Defaults to 8080 locally.
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Web server listening on port {port}")

# ==========================================
# BOT EVENTS
# ==========================================
@bot.event
async def on_ready():
    # Start the dummy web server to keep Render awake
    await start_web_server()

    # Create the trades table with Postgres compatible syntax (SERIAL instead of AUTOINCREMENT)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            trade_id SERIAL PRIMARY KEY,
            user_id BIGINT,
            trader_name TEXT,
            ticker TEXT,
            direction TEXT,
            entry_price REAL,
            closed_price REAL,
            pnl REAL,
            setup TEXT,
            image_url TEXT,
            notes TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    
    # Save the actual trade data using %s placeholders for Postgres
    cursor.execute('''
        INSERT INTO trades (user_id, trader_name, ticker, direction, entry_price, closed_price, pnl, setup, image_url, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING trade_id
    ''', (user_id, trader_name, ticker, direction.value, entry_price, closed_price, pnl, setup, image_url, notes))
    
    # Grab the ID returned by the Postgres insert statement
    trade_id = cursor.fetchone()[0]
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
# ==========================================
@bot.tree.command(name="stats", description="Calculate win rate and total PnL.")
@app_commands.describe(target_user="View stats for a specific user (optional)")
async def stats(interaction: discord.Interaction, target_user: discord.Member = None):
    user = target_user or interaction.user
    
    # Changed ? placeholder to %s for Postgres
    cursor.execute('SELECT pnl FROM trades WHERE user_id = %s', (user.id,))
    trades = cursor.fetchall()
    
    if not trades:
        await interaction.response.send_message(f"{user.display_name} hasn't logged any trades yet.", ephemeral=False)
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
    
    # Changed ? placeholders to %s for Postgres
    cursor.execute('SELECT ticker, pnl FROM trades WHERE trade_id = %s AND user_id = %s', (trade_id, user_id))
    trade = cursor.fetchone()
    
    if not trade:
        await interaction.response.send_message(
            f"❌ Could not find Trade #{trade_id}. It might have already been deleted, or it belongs to another user.", 
            ephemeral=True
        )
        return
        
    ticker, pnl = trade
    
    # Changed ? placeholders to %s for Postgres
    cursor.execute('DELETE FROM trades WHERE trade_id = %s AND user_id = %s', (trade_id, user_id))
    conn.commit()
    
    pnl_string = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
    
    await interaction.response.send_message(
        f"Successfully deleted Trade #{trade_id} ({ticker} : {pnl_string})."
    )

# Run the bot
bot.run(TOKEN)