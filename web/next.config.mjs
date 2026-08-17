const API = process.env.API_ORIGIN || 'http://127.0.0.1:8000'
const target = process.env.BUILD_TARGET || (process.env.BUILD_STATIC === '1' ? 'api' : 'dev')
const repository = process.env.GITHUB_REPOSITORY?.split('/')[1] || ''
const owner = process.env.GITHUB_REPOSITORY?.split('/')[0] || ''
const projectSite = repository && repository !== `${owner}.github.io`
const basePath = target === 'pages' && projectSite ? `/${repository}` : ''

/** @type {import('next').NextConfig} */
const nextConfig = {
  images: { unoptimized: true },
  ...(target === 'pages'
    ? {
        output: 'export',
        trailingSlash: true,
        basePath,
      }
    : target === 'api'
      ? {
          output: 'export',
          distDir: '../api/web',
        }
      : {
          async rewrites() {
            return [{ source: '/api/:path*', destination: `${API}/api/:path*` }]
          },
        }),
}

export default nextConfig
