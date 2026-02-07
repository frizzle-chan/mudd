# Sync Functionality Testing Prompt

This prompt guides testing of the periodic sync functionality in `mudd/cogs/sync.py`.

The testing strategy is: **break things via Discord API and database, then verify sync recovers state**.

## Setup: Lower Sync Interval

Before testing, temporarily lower the sync interval from 15 minutes to 1-2 minutes:

1. Edit `mudd/cogs/sync.py` line 80:
   ```python
   # Change from:
   @tasks.loop(minutes=15)
   # To:
   @tasks.loop(minutes=1)
   ```

2. Start the dev server:
   ```bash
   just dev
   ```

Watch the logs in `.tasks/lastrun.log` or the terminal output.

## Discord API Helper Commands

Use `scripts/discord-e2e` to directly manipulate Discord state and test sync recovery.
The script automatically loads `DISCORD_TOKEN` from `.env`. All commands output JSON
(pipe to `jq` for formatting).

```bash
# Get guild info (bot must be in exactly one guild for dev)
./scripts/discord-e2e get-guild

# List all channels in guild (guild_id auto-detected)
./scripts/discord-e2e list-channels

# List by type
./scripts/discord-e2e list-categories   # type 4
./scripts/discord-e2e list-rooms        # type 0 (text channels)
./scripts/discord-e2e list-forums       # type 15

# Delete a channel (category, text, forum, or thread)
./scripts/discord-e2e delete-channel <channel_id>

# Edit channel topic (to test topic recovery)
./scripts/discord-e2e edit-topic <channel_id> "WRONG TOPIC - sync should fix this"

# Create orphan channel in a category
./scripts/discord-e2e create-channel <guild_id> orphan-test-channel --parent <category_id>

# Rename a channel/forum (to test name recovery)
./scripts/discord-e2e rename-channel <channel_id> wrong-name-inventory

# Unpin a message (to test wallet pin recovery)
./scripts/discord-e2e unpin <channel_id> <message_id>

# Create a forum thread
./scripts/discord-e2e create-thread <forum_id> "Thread Name" "Initial message content"
```

## Database Access

Use PSQL to query and modify database state:

```bash
# Connect to dev database
PGPASSWORD=mudd psql -h db -U mudd -d mudd

# Useful queries:
SELECT * FROM users;
SELECT * FROM rooms;
SELECT * FROM zones;
SELECT * FROM entity_instances WHERE owner_id IS NOT NULL;  -- Inventory items
SELECT * FROM user_inventory_forums;
SELECT * FROM currency_accounts;
```

## Test Scenarios

### 1. Zone Sync (Categories)

**Goal**: Verify sync creates Discord categories for zones and handles missing ones.

**Test - Delete category via API**:
1. Find a zone category ID:
   ```bash
   ./scripts/discord-e2e list-categories | jq '.[] | {id, name}'
   ```
2. Delete the category:
   ```bash
   ./scripts/discord-e2e delete-channel <category_id>
   ```
3. Wait for sync (check logs for "Zone sync:")
4. **Verify**: Category recreated with fog-of-war permissions (`@everyone` view_channel=False)

**SQL to check zones**:
```sql
SELECT * FROM zones;
```

### 2. Room Sync (Channels)

**Goal**: Verify sync creates channels and fixes topics.

**Test A - Delete channel via API**:
1. Find a room channel ID:
   ```bash
   ./scripts/discord-e2e list-rooms | jq '.[] | {id, name, parent_id}'
   ```
2. Delete the channel:
   ```bash
   ./scripts/discord-e2e delete-channel <channel_id>
   ```
3. Wait for sync
4. **Verify**: Channel recreated in correct category with description as topic

**Test B - Corrupt topic via API**:
1. Change a channel's topic:
   ```bash
   ./scripts/discord-e2e edit-topic <channel_id> "CORRUPTED - sync should restore this"
   ```
2. Wait for sync
3. **Verify**: Topic restored to room description from database

**SQL to check rooms**:
```sql
SELECT id, name, description, zone_id FROM rooms;
```

### 3. Orphan Channel Detection

**Goal**: Verify sync detects channels that don't match any room ID.

**Test - Create orphan via API**:
1. Find a zone category ID:
   ```bash
   ./scripts/discord-e2e list-categories | jq '.[] | {id, name}'
   ```
2. Get the guild ID:
   ```bash
   ./scripts/discord-e2e get-guild | jq -r '.id'
   ```
3. Create orphan channel in that category:
   ```bash
   ./scripts/discord-e2e create-channel <guild_id> orphan-test-channel --parent <category_id>
   ```
4. Wait for sync
5. **Verify**: Message in #console: "Orphan channel detected: #orphan-test-channel"
6. Wait for next sync
7. **Verify**: No duplicate message (orphans only reported once)
8. Clean up: Delete the orphan channel manually or via API

### 4. Visibility Sync (User Permissions)

**Goal**: Verify sync updates channel permissions based on user locations.

**Test**:
1. Move a user to a different room via SQL:
   ```sql
   UPDATE users SET current_room = 'library' WHERE id = <user_id>;
   ```
2. Wait for sync
3. **Verify**: User can now see #library channel, cannot see previous room

**SQL to check user locations**:
```sql
SELECT u.id, u.current_room, r.zone_id
FROM users u
JOIN rooms r ON u.current_room = r.id;
```

### 5. Inventory Forum Sync

**Goal**: Verify sync creates/recovers inventory forums for all users.

**Test A - Delete forum via API**:
1. Find inventory forums:
   ```bash
   ./scripts/discord-e2e list-forums | jq '.[] | {id, name, parent_id}'
   ```
2. Delete a user's inventory forum:
   ```bash
   ./scripts/discord-e2e delete-channel <forum_id>
   ```
3. Also delete the DB record:
   ```sql
   DELETE FROM user_inventory_forums WHERE user_id = <user_id>;
   ```
4. Wait for sync
5. **Verify**: Forum recreated with name `<username>-inventory`

**Test B - Forum recovery (DB loss only)**:
1. Delete only the DB record (keep Discord forum intact):
   ```sql
   DELETE FROM user_inventory_forums WHERE user_id = <user_id>;
   ```
2. Wait for sync
3. **Verify**: Logs show "Recovered inventory forum" (finds existing Discord forum by name)

**Test C - Rename forum via API (simulate username change)**:
1. Rename forum to wrong name:
   ```bash
   ./scripts/discord-e2e rename-channel <forum_id> wrong-name-inventory
   ```
2. Wait for sync
3. **Verify**: Forum renamed back to `<username>-inventory`

**SQL to check forums**:
```sql
SELECT * FROM user_inventory_forums;
```

### 6. Wallet Sync

**Goal**: Verify sync creates wallets with pinned threads.

**Test A - Delete wallet thread via API**:
1. Find wallet thread ID from DB:
   ```sql
   SELECT ei.discord_thread_id FROM entity_instances ei
   WHERE ei.entity_id = 'wallet' AND ei.owner_id = <user_id>;
   ```
2. Delete the thread via API:
   ```bash
   ./scripts/discord-e2e delete-channel <thread_id>
   ```
3. Wait for sync
4. **Verify**: Thread recreated and pinned

**Test B - Full wallet deletion**:
1. Delete wallet thread via API (as above)
2. Delete DB records:
   ```sql
   DELETE FROM entity_instances WHERE entity_id = 'wallet' AND owner_id = <user_id>;
   DELETE FROM currency_accounts WHERE user_id = <user_id>;
   ```
3. Wait for sync
4. **Verify**:
   - New wallet entity instance created
   - Thread created in user's inventory forum
   - Thread is pinned
   - Description shows balance (default: 1000)

**SQL to check wallets**:
```sql
SELECT ca.user_id, ca.balance, ca.wallet_instance_id, ei.discord_thread_id
FROM currency_accounts ca
LEFT JOIN entity_instances ei ON ca.wallet_instance_id::uuid = ei.id;
```

### 7. Inventory Thread Sync

**Goal**: Verify sync creates threads for inventory items and updates descriptions.

**Test A - Delete item thread via API**:
1. Find an item's thread ID (not wallet):
   ```sql
   SELECT ei.id, ei.entity_id, e.name, ei.discord_thread_id
   FROM entity_instances ei
   JOIN entities e ON ei.entity_id = e.id
   WHERE ei.owner_id = <user_id> AND ei.entity_id != 'wallet';
   ```
2. Delete the thread via API:
   ```bash
   ./scripts/discord-e2e delete-channel <thread_id>
   ```
3. Wait for sync
4. **Verify**: Thread recreated with item description

**Test B - Stale description**:
1. Edit an entity's `on_look` in `data/worlds/mansion.rec`
2. Wait for sync (entity sync updates DB, then inventory sync updates thread)
3. **Verify**: Thread description updated to new content

**SQL to check inventory**:
```sql
SELECT ei.id, ei.entity_id, e.name, ei.owner_id, ei.discord_thread_id
FROM entity_instances ei
JOIN entities e ON ei.entity_id = e.id
WHERE ei.owner_id IS NOT NULL;
```

### 8. Orphan Thread Pruning

**Goal**: Verify sync removes threads for items no longer in inventory.

**Test - Create orphan thread via API**:
1. Find a user's inventory forum ID:
   ```sql
   SELECT forum_id FROM user_inventory_forums WHERE user_id = <user_id>;
   ```
2. Create an orphan thread in the forum:
   ```bash
   ./scripts/discord-e2e create-thread <forum_id> orphan-item-thread "This should be pruned"
   ```
3. Wait for sync
4. **Verify**: Orphan thread deleted (logs show "threads_pruned: 1" or higher)

### 9. Spawning Pool Respawns

**Goal**: Verify respawn task creates items from spawning pools.

**Note**: Respawn task runs every 1 minute (separate from periodic sync).

**Test**:
1. Check spawning pool configuration:
   ```sql
   SELECT * FROM spawning_pools;
   ```
2. Delete spawned items:
   ```sql
   DELETE FROM entity_instances WHERE spawning_pool_id IS NOT NULL;
   ```
3. Wait for respawn task (up to 1 minute)
4. **Verify**: Logs show "Spawned X items from spawning pools"

**SQL to check spawned items**:
```sql
SELECT sp.id AS pool_id, sp.room, sp.max_count, COUNT(ei.id) AS current_count
FROM spawning_pools sp
LEFT JOIN entity_instances ei ON ei.spawning_pool_id = sp.id
GROUP BY sp.id, sp.room, sp.max_count;
```

## Log Messages to Watch

Expected log messages during sync:

```
Starting initial sync (first run)
Zone sync: X synced, Y deleted
Room sync: X synced, Y deleted, Z users relocated
Visibility sync for <guild>: VisibilityStats(...)
Inventory sync for <guild>: X users, {'created': ..., 'recovered': ..., ...}
Initial sync complete
```

For subsequent syncs (every 1-2 minutes):
```
Zone sync: X synced, 0 deleted
Room sync: X synced, 0 deleted, 0 users relocated
Visibility sync for <guild>: VisibilityStats(...)
Inventory sync for <guild>: X users, {...}
```

Spawning pool logs (every minute):
```
Spawned X items from spawning pools
```

## Fixing Errors in This Prompt

If you encounter errors during testing (API calls fail, instructions are incorrect, commands don't work as expected), **edit this `prompt.local.md` file** to fix the issue for future runs.

Common fixes:
- API endpoint changed → Update the curl command
- SQL query fails → Fix the query syntax or table/column names
- Channel type numbers wrong → Update the `jq` filter
- Missing steps → Add clarifying instructions
- Incorrect assumptions → Document the actual behavior

This prompt is a living document. Improve it as you test.

## Cleanup

After testing, restore the sync interval to its original value (15 minutes):

```bash
git checkout mudd/cogs/sync.py
```

## Success Criteria

All tests pass if:

1. Categories recreated when deleted
2. Channels recreated with correct topics
3. Orphan channels reported once to #console
4. User permissions match their `current_room`
5. Inventory forums created/recovered for all non-bot members
6. Wallet threads exist and are pinned
7. Inventory item threads match DB state
8. Orphan threads pruned
9. Spawning pools respawn items up to max_count

