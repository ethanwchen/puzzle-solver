#!/bin/zsh
# Run one harness test: ./run.sh NAME URL [drive.js options...]
#   ./run.sh g9 https://example.test/hunt/game-9 --intro 40
cd "$(dirname "$0")"
NAME=$1; URL=$2; shift 2
PORT=${PORT:-9448}
SRC=${TMPDIR:-/tmp}/sidekick-harness-$NAME; rm -rf $SRC; mkdir -p $SRC
lsof -ti tcp:8777 >/dev/null || (python3 -m http.server 8777 --bind 127.0.0.1 >/dev/null 2>&1 &)
(cd ../sidekick && SIDEKICK_SOURCE=$SRC ./node_modules/.bin/electron . --remote-debugging-port=$PORT >$SRC/app.log 2>&1 &)
for i in {1..120}; do curl -s http://127.0.0.1:$PORT/json 2>/dev/null | grep -q 'Sidekick' && break; sleep 0.5; done
node drive.js "$URL" $SRC $PORT "$@"
pkill -f "remote-debugging-port=$PORT" 2>/dev/null
echo "session: $(grep -m1 SESSION $SRC/app.log | cut -d" " -f2)"
