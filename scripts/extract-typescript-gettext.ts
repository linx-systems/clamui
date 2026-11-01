import ts from "../desktop/node_modules/typescript/lib/typescript.js";

const [filesFrom, outputFiles, outputDirectory] = Bun.argv.slice(2);

if (!filesFrom || !outputFiles || !outputDirectory) {
  throw new Error("Usage: bun scripts/extract-typescript-gettext.ts FILES_FROM OUTPUT_FILES OUTPUT_DIRECTORY");
}

const files = (await Bun.file(filesFrom).text())
  .split(/\r?\n/)
  .filter((file) => file.length > 0);

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

function staticString(node: ts.Expression | undefined): string | undefined {
  if (node && (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node))) {
    return node.text;
  }
  return undefined;
}

function translatorComments(source: string, sourceFile: ts.SourceFile, node: ts.Expression): string[] {
  const ranges = ts.getLeadingCommentRanges(source, node.getFullStart()) ?? [];
  const comments: string[] = [];
  let nextStart = node.getStart(sourceFile);

  for (let index = ranges.length - 1; index >= 0; index -= 1) {
    const range = ranges[index];
    if (source.slice(range.end, nextStart).trim().length > 0) break;

    const raw = source.slice(range.pos, range.end);
    if (!raw.startsWith("//")) break;

    const comment = raw.slice(2).trimStart();
    if (!comment.startsWith("Translators:")) break;

    comments.unshift(comment);
    nextStart = range.pos;
  }

  return comments;
}


function scriptKind(path: string): ts.ScriptKind {
  if (path.endsWith(".tsx")) return ts.ScriptKind.TSX;
  if (path.endsWith(".ts")) return ts.ScriptKind.TS;
  return ts.ScriptKind.Unknown;
}

const compatibleFiles: string[] = [];
for (const [index, path] of files.entries()) {
  const source = await Bun.file(path).text();
  const sourceFile = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, false, scriptKind(path));
  const calls: string[] = [];

  const emitCall = (
    node: ts.CallExpression,
    name: "_" | "ngettext" | "pgettext",
    messages: string[],
    messageNodes: ts.Expression[],
  ) => {
    const { line } = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile));
    const comments = messageNodes.flatMap((messageNode) => translatorComments(source, sourceFile, messageNode));
    const location = `#line ${line + 1} ${cString(path)}`;
    const call = `${name}(${messages.map(cString).join(", ")});`;
    calls.push(comments.length > 0
      ? `#line ${line + 1 - comments.length} ${cString(path)}\n${comments.map((comment) => `// ${comment}`).join("\n")}\n${call}`
      : `${location}\n${call}`);
  };

  const visit = (node: ts.Node): void => {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
      const { text: name } = node.expression;
      if (name === "_") {
        const message = staticString(node.arguments[0]);
        if (message !== undefined) emitCall(node, name, [message], [node.arguments[0]]);
      } else if (name === "ngettext") {
        const single = staticString(node.arguments[0]);
        const plural = staticString(node.arguments[1]);
        if (single !== undefined && plural !== undefined) {
          emitCall(node, name, [single, plural], [node.arguments[0], node.arguments[1]]);
        }
      } else if (name === "pgettext") {
        const context = staticString(node.arguments[0]);
        const message = staticString(node.arguments[1]);
        if (context !== undefined && message !== undefined) {
          emitCall(node, name, [context, message], [node.arguments[0], node.arguments[1]]);
        }
      }
    }
    ts.forEachChild(node, visit);
  };

  visit(sourceFile);
  if (calls.length > 0) {
    const compatible = `${outputDirectory}/typescript-${index + 1}.c`;
    await Bun.write(compatible, `${calls.join("\n")}\n`);
    compatibleFiles.push(compatible);
  }
}

await Bun.write(outputFiles, compatibleFiles.length > 0 ? `${compatibleFiles.join("\n")}\n` : "");
