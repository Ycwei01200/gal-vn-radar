declare module "node:fs/promises" {
  export function readFile(
    path: string | URL,
    encoding: "utf8",
  ): Promise<string>;
}
