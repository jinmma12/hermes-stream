using Hermes.Api.Options;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;

namespace Hermes.Api.Persistence;

public sealed class HermesApiDbContext : DbContext
{
    private readonly DatabaseOptions _options;

    public HermesApiDbContext(
        DbContextOptions<HermesApiDbContext> options,
        IOptions<DatabaseOptions> databaseOptions) : base(options)
    {
        _options = databaseOptions.Value;
    }

    public DbSet<SchemaRevision> SchemaRevisions => Set<SchemaRevision>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        var schema = string.IsNullOrWhiteSpace(_options.Schema) ? "hermes" : _options.Schema.Trim();

        modelBuilder.HasDefaultSchema(schema);

        modelBuilder.Entity<SchemaRevision>(builder =>
        {
            builder.ToTable("schema_revisions");
            builder.HasKey(x => x.Id);
            builder.Property(x => x.Id).HasColumnName("id");
            builder.Property(x => x.Provider).HasColumnName("provider").HasMaxLength(32);
            builder.Property(x => x.SchemaName).HasColumnName("schema_name").HasMaxLength(128);
            builder.Property(x => x.RevisionKey).HasColumnName("revision_key").HasMaxLength(128);
            builder.Property(x => x.AppliedBy).HasColumnName("applied_by").HasMaxLength(128);
            builder.Property(x => x.Notes).HasColumnName("notes").HasMaxLength(2000);
            builder.Property(x => x.AppliedAt).HasColumnName("applied_at");
            builder.HasIndex(x => new { x.Provider, x.SchemaName, x.RevisionKey }).IsUnique();
        });
    }
}
