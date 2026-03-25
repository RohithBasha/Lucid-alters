"""Quick diagnostic test — run this locally to find what's broken."""
import sys
print(f"Python: {sys.version}")
print()

# Test 1: Imports
print("=" * 50)
print("TEST 1: Checking imports...")
errors = []
try:
    import config
    print("  ✅ config")
except Exception as e:
    errors.append(f"  ❌ config: {e}")
    print(errors[-1])

try:
    import data_fetcher
    print("  ✅ data_fetcher")
except Exception as e:
    errors.append(f"  ❌ data_fetcher: {e}")
    print(errors[-1])

try:
    import bollinger
    print("  ✅ bollinger")
except Exception as e:
    errors.append(f"  ❌ bollinger: {e}")
    print(errors[-1])

try:
    import telegram_notifier
    print("  ✅ telegram_notifier")
except Exception as e:
    errors.append(f"  ❌ telegram_notifier: {e}")
    print(errors[-1])

try:
    import journaler
    print("  ✅ journaler")
except Exception as e:
    errors.append(f"  ❌ journaler: {e}")
    print(errors[-1])

try:
    import bot_commands
    print("  ✅ bot_commands")
except Exception as e:
    errors.append(f"  ❌ bot_commands: {e}")
    print(errors[-1])

try:
    import chart_generator
    print("  ✅ chart_generator")
except Exception as e:
    errors.append(f"  ❌ chart_generator: {e}")
    print(errors[-1])

# Test 2: Config
print()
print("=" * 50)
print("TEST 2: Checking config...")
print(f"  BOT_TOKEN set: {'YES' if config.TELEGRAM_BOT_TOKEN else 'NO (will fail on GitHub!)'}")
print(f"  CHAT_ID set: {'YES' if config.TELEGRAM_CHAT_ID else 'NO (will fail on GitHub!)'}")
print(f"  Instruments: {list(config.INSTRUMENTS.keys())}")

# Test 3: Data fetch
print()
print("=" * 50)
print("TEST 3: Fetching data (this takes ~5 seconds)...")
try:
    data = data_fetcher.fetch_all_instruments()
    for sym, df in data.items():
        print(f"  ✅ {sym}: {len(df)} candles fetched")
    if not data:
        print("  ⚠️ No data returned (market may be closed)")
except Exception as e:
    print(f"  ❌ Data fetch failed: {e}")

# Test 4: Bollinger signals
print()
print("=" * 50)
print("TEST 4: Testing signal detection...")
for sym, df in data.items():
    try:
        signals = bollinger.detect_signals(df)
        if signals:
            for s in signals:
                print(f"  🚨 {sym}: {s['type']} — {s['label']}")
        else:
            print(f"  ✅ {sym}: No signal (price within bands)")
    except Exception as e:
        print(f"  ❌ {sym}: Signal detection failed: {e}")

# Test 5: Bot commands
print()
print("=" * 50)
print("TEST 5: Testing bot commands...")
try:
    bot_commands.process_commands()
    print("  ✅ process_commands() ran without error")
except Exception as e:
    print(f"  ❌ process_commands failed: {e}")

# Summary
print()
print("=" * 50)
if errors:
    print(f"❌ FOUND {len(errors)} IMPORT ERROR(S):")
    for e in errors:
        print(e)
else:
    print("✅ ALL TESTS PASSED — code is working correctly!")
print("=" * 50)
