/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  transpilePackages: ['@zerna/sdk'],
  experimental: {
    serverActions: {
      bodySizeLimit: '3gb',
    },
  },
};

export default nextConfig;
