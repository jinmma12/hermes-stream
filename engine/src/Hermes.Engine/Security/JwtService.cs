using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Text;
using Microsoft.IdentityModel.Tokens;

namespace Hermes.Engine.Security;

public interface IJwtService
{
    string GenerateToken(HermesUser user);
    ClaimsPrincipal? ValidateToken(string token);
    HermesUser? GetUserFromClaims(ClaimsPrincipal principal);
}

public class JwtConfig
{
    public string Secret { get; set; } = "hermes-default-secret-change-in-production-min-32-chars!!";
    public string Issuer { get; set; } = "hermes-engine";
    public string Audience { get; set; } = "hermes-clients";
    public int ExpirationMinutes { get; set; } = 480; // 8 hours
}

public class JwtService : IJwtService
{
    private readonly JwtConfig _config;

    public JwtService(JwtConfig config) => _config = config;

    public string GenerateToken(HermesUser user)
    {
        var key = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(_config.Secret));
        var credentials = new SigningCredentials(key, SecurityAlgorithms.HmacSha256);

        var claims = new[]
        {
            new Claim(JwtRegisteredClaimNames.Sub, user.UserId),
            new Claim(JwtRegisteredClaimNames.Email, user.Email),
            new Claim("name", user.UserName),
            new Claim(ClaimTypes.Role, user.Role.ToString()),
            new Claim("tenant_id", user.TenantId ?? "default"),
            new Claim(JwtRegisteredClaimNames.Jti, Guid.NewGuid().ToString()),
        };

        var token = new JwtSecurityToken(
            issuer: _config.Issuer,
            audience: _config.Audience,
            claims: claims,
            expires: DateTime.UtcNow.AddMinutes(_config.ExpirationMinutes),
            signingCredentials: credentials);

        return new JwtSecurityTokenHandler().WriteToken(token);
    }

    public ClaimsPrincipal? ValidateToken(string token)
    {
        var key = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(_config.Secret));
        var handler = new JwtSecurityTokenHandler();

        try
        {
            return handler.ValidateToken(token, new TokenValidationParameters
            {
                ValidateIssuer = true,
                ValidIssuer = _config.Issuer,
                ValidateAudience = true,
                ValidAudience = _config.Audience,
                ValidateIssuerSigningKey = true,
                IssuerSigningKey = key,
                ValidateLifetime = true,
                ClockSkew = TimeSpan.FromMinutes(1)
            }, out _);
        }
        catch
        {
            return null;
        }
    }

    public HermesUser? GetUserFromClaims(ClaimsPrincipal principal)
    {
        var userId = principal.FindFirst(JwtRegisteredClaimNames.Sub)?.Value;
        if (userId == null) return null;

        return new HermesUser(
            UserId: userId,
            UserName: principal.FindFirst("name")?.Value ?? "",
            Email: principal.FindFirst(JwtRegisteredClaimNames.Email)?.Value ?? "",
            Role: Enum.TryParse<Role>(principal.FindFirst(ClaimTypes.Role)?.Value, out var role) ? role : Role.Viewer,
            TenantId: principal.FindFirst("tenant_id")?.Value);
    }
}
