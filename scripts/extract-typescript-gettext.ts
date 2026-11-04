import { parse } from "../desktop/node_modules/@babel/parser";

type AstNode = {
  type: string;
  start: number;
  end: number;
  loc: { start: { line: number } };
  [key: string]: unknown;
};

type SourceComment = {
  type: string;
  value: string;
  start: number;
  end: number;
};

export type ExtractedMessage = {
  name: "_" | "ngettext" | "pgettext";
  messages: string[];
  line: number;
  comments: string[];
};

function cString(value: string): string {
  return `"${value.replace(/[\\"\u0000-\u001f]/g, (character) => {
    switch (character) {
      case "\\": return "\\\\";
      case "\"": return "\\\"";
      case "\b": return "\\b";
      case "\f": return "\\f";
      case "\n": return "\\n";
      case "\r": return "\\r";
      case "\t": return "\\t";
      case "\v": return "\\v";
      default: return `\\${character.charCodeAt(0).toString(8).padStart(3, "0")}`;
    }
  })}"`;
}

function isNode(value: unknown): value is AstNode {
  return typeof value === "object"
    && value !== null
    && "type" in value
    && typeof value.type === "string"
    && "start" in value
    && typeof value.start === "number"
    && "end" in value
    && typeof value.end === "number"
    && "loc" in value
    && typeof value.loc === "object"
    && value.loc !== null
    && "start" in value.loc
    && typeof value.loc.start === "object"
    && value.loc.start !== null
    && "line" in value.loc.start
    && typeof value.loc.start.line === "number";
}

function staticString(node: AstNode | undefined): string | undefined {
  if (node?.type === "StringLiteral" && typeof node.value === "string") {
    return node.value;
  }
  if (
    node?.type === "TemplateLiteral"
    && Array.isArray(node.expressions)
    && node.expressions.length === 0
    && Array.isArray(node.quasis)
    && node.quasis.length === 1
  ) {
    const quasi = node.quasis[0];
    if (
      typeof quasi === "object"
      && quasi !== null
      && "value" in quasi
      && typeof quasi.value === "object"
      && quasi.value !== null
    ) {
      if ("cooked" in quasi.value && typeof quasi.value.cooked === "string") {
        return quasi.value.cooked;
      }
      if ("raw" in quasi.value && typeof quasi.value.raw === "string") {
        return quasi.value.raw;
      }
    }
  }
  return undefined;
}

function translatorComments(source: string, comments: readonly SourceComment[], node: AstNode): string[] {
  const extracted: string[] = [];
  let nextStart = node.start;

  for (let index = comments.length - 1; index >= 0; index -= 1) {
    const comment = comments[index];
    if (comment.end > nextStart) continue;
    if (source.slice(comment.end, nextStart).trim().length > 0) break;
    if (comment.type !== "CommentLine") break;

    const text = comment.value.trimStart();
    if (!text.startsWith("Translators:")) break;

    extracted.unshift(text);
    nextStart = comment.start;
  }

  return extracted;
}

function childNodes(node: AstNode): AstNode[] {
  const children: AstNode[] = [];
  for (const [key, value] of Object.entries(node)) {
    if (
      key === "type"
      || key === "start"
      || key === "end"
      || key === "loc"
      || key === "extra"
      || key === "comments"
      || key === "leadingComments"
      || key === "innerComments"
      || key === "trailingComments"
    ) {
      continue;
    }
    if (isNode(value)) {
      children.push(value);
    } else if (Array.isArray(value)) {
      children.push(...value.filter(isNode));
    }
  }
  return children;
}

function isComment(value: unknown): value is SourceComment {
  return typeof value === "object"
    && value !== null
    && "type" in value
    && typeof value.type === "string"
    && "value" in value
    && typeof value.value === "string"
    && "start" in value
    && typeof value.start === "number"
    && "end" in value
    && typeof value.end === "number";
}

export function extractTypeScriptGettext(source: string, sourceName = "TypeScript source"): ExtractedMessage[] {
  let parsed;
  try {
    parsed = parse(source, {
      sourceType: "module",
      plugins: sourceName.endsWith(".tsx") ? ["typescript", "jsx"] : ["typescript"],
      attachComment: false,
    });
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`Unable to parse ${sourceName}: ${detail}`, { cause: error });
  }

  const comments = (parsed.comments ?? []).filter(isComment);
  const messages: ExtractedMessage[] = [];

  const visit = (node: AstNode): void => {
    if (
      (node.type === "CallExpression" || node.type === "OptionalCallExpression")
      && isNode(node.callee)
      && node.callee.type === "Identifier"
      && typeof node.callee.name === "string"
      && Array.isArray(node.arguments)
    ) {
      const name = node.callee.name;
      const arguments_ = node.arguments.filter(isNode);
      const add = (messageName: ExtractedMessage["name"], strings: string[], nodes: AstNode[]) => {
        messages.push({
          name: messageName,
          messages: strings,
          line: node.loc.start.line,
          comments: nodes.flatMap((argument_) => translatorComments(source, comments, argument_)),
        });
      };
      if (name === "_") {
        const message = staticString(arguments_[0]);
        if (message !== undefined) add(name, [message], [arguments_[0]]);
      } else if (name === "ngettext") {
        const single = staticString(arguments_[0]);
        const plural = staticString(arguments_[1]);
        if (single !== undefined && plural !== undefined) {
          add(name, [single, plural], [arguments_[0], arguments_[1]]);
        }
      } else if (name === "pgettext") {
        const context = staticString(arguments_[0]);
        const message = staticString(arguments_[1]);
        if (context !== undefined && message !== undefined) {
          add(name, [context, message], [arguments_[0], arguments_[1]]);
        }
      }
    }
    for (const child of childNodes(node)) visit(child);
  };

  if (!isNode(parsed.program)) {
    throw new Error(`Unable to parse ${sourceName}: parser returned no program`);
  }
  visit(parsed.program);
  return messages;
}

function renderCompatibleCall(message: ExtractedMessage, path: string): string {
  const location = `#line ${message.line} ${cString(path)}`;
  const call = `${message.name}(${message.messages.map(cString).join(", ")});`;
  return message.comments.length > 0
    ? `#line ${message.line - message.comments.length} ${cString(path)}\n${message.comments.map((comment) => `// ${comment}`).join("\n")}\n${call}`
    : `${location}\n${call}`;
}

async function main(): Promise<void> {
  const [filesFrom, outputFiles, outputDirectory] = Bun.argv.slice(2);
  if (!filesFrom || !outputFiles || !outputDirectory) {
    throw new Error("Usage: bun scripts/extract-typescript-gettext.ts FILES_FROM OUTPUT_FILES OUTPUT_DIRECTORY");
  }
  const files = (await Bun.file(filesFrom).text())
    .split(/\r?\n/)
    .filter((file) => file.length > 0);
  const compatibleFiles: string[] = [];

  for (const [index, path] of files.entries()) {
    const source = await Bun.file(path).text();
    const calls = extractTypeScriptGettext(source, path).map((message) => renderCompatibleCall(message, path));
    if (calls.length > 0) {
      const compatible = `${outputDirectory}/typescript-${index + 1}.c`;
      await Bun.write(compatible, `${calls.join("\n")}\n`);
      compatibleFiles.push(compatible);
    }
  }

  await Bun.write(outputFiles, compatibleFiles.length > 0 ? `${compatibleFiles.join("\n")}\n` : "");
}

if (import.meta.main) {
  await main();
}
