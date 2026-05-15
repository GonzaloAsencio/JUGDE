/** @type {import('jest').Config} */
const config = {
  preset: 'ts-jest',
  testEnvironment: 'jsdom',
  setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/$1',
    // Mock ESM-only packages that jest cannot transform
    '^react-markdown$': '<rootDir>/__mocks__/react-markdown.tsx',
    '^remark-gfm$': '<rootDir>/__mocks__/remark-gfm.ts',
    '^rehype-slug$': '<rootDir>/__mocks__/rehype-slug.ts',
    '^rehype-autolink-headings$': '<rootDir>/__mocks__/rehype-autolink-headings.ts',
  },
};
module.exports = config;
