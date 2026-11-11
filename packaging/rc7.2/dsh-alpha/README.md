# dsh-alpha offline installation gate

Pinned upstream: \`songofhawk/dsh-alpha\` 0.2.2 at \`f417e90ddd0e20f08b82e0b79a8c29fdad45c8f4\`.

This package deliberately does not include upstream source bytes. GitHub reports no declared license for the repository. Commercial use and redistribution permission have not been established. Do not install or redistribute the plugin in a bank environment until Legal/Procurement records explicit permission.

To install after authorization, obtain the exact pinned source archive through the bank-approved channel and create an authorization record:

\`\`\`json
{
  "upstream": "songofhawk/dsh-alpha",
  "version": "0.2.2",
  "source_commit": "f417e90ddd0e20f08b82e0b79a8c29fdad45c8f4",
  "commercial_use_authorized": true,
  "redistribution_authorized": true,
  "authorization_reference": "BANK-LEGAL-APPROVAL-ID"
}
\`\`\`

The archive must contain \`package.json\`, production dependency \`node_modules/@deepseek-ai/schemastery\`, and a root \`SOURCE_COMMIT\` file with the exact pinned commit. This is package-local staging only; enabling the plugin in a selected DSH profile and running the upstream preset/profile installer remain a separate bank-approved activation step. Then run:

\`\`\`bash
bash packaging/rc7.2/dsh-alpha/install-dsh-alpha.sh \\
  /path/to/authorized-dsh-alpha.tar.gz \\
  /path/to/dsh-alpha-authorization.json \\
  <archive-sha256>
\`\`\`

The installer validates the authorization record, archive SHA-256, package name/version and commit marker before materializing files into the package-local DSH plugin directory. It does not download anything.
