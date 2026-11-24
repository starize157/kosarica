"""Ustvari data/db.json z vzorčnimi strankami in naročili."""

from store import seed_database

if __name__ == "__main__":
    stats = seed_database()
    print(f"Baza je pripravljena: {stats['customers']} strank, {stats['active']} aktivnih naročnin.")
    print(f"Mesečni prihodek: {stats['mrr']} €")
    print(f"Košarice ta teden ({stats['weekLabel']}): {stats['weekBaskets']}")
    print(f"Menjave ta teden: {stats['swaps']}")
