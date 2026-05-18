// PM2 ecosystem file. Two processes run side-by-side, both reading their
// env from backend/.env via dotenv (the email-worker resolves it relative
// to its own location). Start with:
//
//   pm2 start deploy/ecosystem.config.cjs
//   pm2 save                                    # persist for boot
//
// Restart after a deploy:  pm2 restart all
// Tail logs:               pm2 logs
// Status:                  pm2 status

module.exports = {
  apps: [
    {
      name: 'wedding-backend',
      cwd: '/opt/wedding/backend',
      script: './dist/index.js',
      instances: 1,
      autorestart: true,
      max_memory_restart: '512M',
      env: {
        NODE_ENV: 'production',
      },
      out_file:   '/var/log/wedding/backend.out.log',
      error_file: '/var/log/wedding/backend.err.log',
      merge_logs: true,
      time: true,
    },
    {
      name: 'wedding-email',
      cwd: '/opt/wedding/email-worker',
      script: './dist/index.js',
      instances: 1,
      autorestart: true,
      max_memory_restart: '256M',
      env: {
        NODE_ENV: 'production',
      },
      out_file:   '/var/log/wedding/email.out.log',
      error_file: '/var/log/wedding/email.err.log',
      merge_logs: true,
      time: true,
    },
  ],
};
