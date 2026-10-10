import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // @orion/shared ships raw TypeScript, so Next has to compile it.
  transpilePackages: ["@orion/shared"],
};

export default nextConfig;
