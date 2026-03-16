import sqlite3
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

DATABASE = "bot_data.db"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def db():
    return sqlite3.connect(DATABASE)

@app.get("/api/health")
def health():
    return {"ok": True}

@app.get("/api/portfolio/{user_id}")
def portfolio(user_id: int):
    with db() as conn:
        cur = conn.cursor()

        cur.execute(
            "SELECT asset, free, locked FROM balances WHERE user_id = ? ORDER BY asset",
            (user_id,),
        )
        balances = [
            {"asset": row[0], "free": row[1], "locked": row[2]}
            for row in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT id, symbol, side, size, entry_price, mark_price, pnl
            FROM positions
            WHERE user_id = ? AND status = 'open'
            ORDER BY id DESC
            """,
            (user_id,),
        )
        positions = [
            {
                "id": row[0],
                "symbol": row[1],
                "side": row[2],
                "size": row[3],
                "entry_price": row[4],
                "mark_price": row[5],
                "pnl": row[6],
            }
            for row in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT id, symbol, side, order_type, price, amount, status, created_at
            FROM orders
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 10
            """,
            (user_id,),
        )
        orders = [
            {
                "id": row[0],
                "symbol": row[1],
                "side": row[2],
                "type": row[3],
                "price": row[4],
                "amount": row[5],
                "status": row[6],
                "created_at": row[7],
            }
            for row in cur.fetchall()
        ]

    if not balances and not positions and not orders:
        raise HTTPException(status_code=404, detail="User not found or no data")

    return {
        "balances": balances,
        "positions": positions,
        "orders": orders,
    }
