namespace Hermes.Engine.Security;

public enum Role { Viewer, Operator, Admin }

public record HermesUser(
    string UserId,
    string UserName,
    string Email,
    Role Role,
    string? TenantId = null);

public record LoginRequest(string Username, string Password);
public record LoginResponse(string Token, string RefreshToken, long ExpiresIn, HermesUser User);

public record AuditEntry
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public string UserId { get; set; } = string.Empty;
    public string UserName { get; set; } = string.Empty;
    public string Action { get; set; } = string.Empty;   // CREATE_PIPELINE, ACTIVATE, MODIFY_RECIPE, etc.
    public string Resource { get; set; } = string.Empty;  // pipeline:123, recipe:456
    public string? Detail { get; set; }                   // JSON detail
    public string? IpAddress { get; set; }
    public DateTimeOffset Timestamp { get; set; } = DateTimeOffset.UtcNow;
}
