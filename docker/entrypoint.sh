#!/bin/sh
set -e

cat > /usr/share/nginx/html/assets/env.js << EOF
window.__env = {
  googleMapsApiKey: '${GOOGLE_MAPS_API_KEY}',
};
EOF

exec nginx -g "daemon off;"
