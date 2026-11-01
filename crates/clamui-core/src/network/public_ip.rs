//! Conservative eligibility policy for VirusTotal IP report links.
//!
//! This intentionally rejects special-use address space even where a small
//! subset could be globally routable. A report URL discloses the IP to an
//! external service, so false positives are less acceptable than false
//! negatives.

/// Returns the fixed VirusTotal report URL only for conservatively public IPs.
///
/// The caller has already parsed an address and rejects scoped IPv6 addresses
/// before calling this function. This policy neither performs network I/O nor
/// converts IPv4-mapped IPv6 addresses into IPv4.
pub(super) fn virustotal_url(address: std::net::IpAddr) -> Option<String> {
    let eligible = match address {
        std::net::IpAddr::V4(address) => eligible_ipv4(address.octets()),
        std::net::IpAddr::V6(address) => eligible_ipv6(address.segments()),
    };

    eligible.then(|| format!("https://www.virustotal.com/gui/ip-address/{address}/detection"))
}

fn eligible_ipv4(octets: [u8; 4]) -> bool {
    let [first, second, third, _] = octets;

    !matches!(
        (first, second, third),
        (0, _, _)
            | (10, _, _)
            | (100, 64..=127, _)
            | (127, _, _)
            | (169, 254, _)
            | (172, 16..=31, _)
            | (192, 0, 0 | 2)
            | (192, 88, 99)
            | (192, 168, _)
            | (198, 18..=19, _)
            | (198, 51, 100)
            | (203, 0, 113)
            | (224..=u8::MAX, _, _)
    )
}

fn eligible_ipv6(segments: [u16; 8]) -> bool {
    let [first, second, ..] = segments;

    // Native global-unicast space is 2000::/3. The exclusions are deliberately
    // broader than strictly unroutable space to avoid special-use disclosure.
    (0x2000..=0x3fff).contains(&first)
        && !matches!(
            (first, second),
            (0x2001, 0x0000..=0x01ff)
                | (0x2001, 0x0db8)
                | (0x2002, _)
                | (0x3ffe, _)
                | (0x3fff, 0x0000..=0x0fff)
        )
}

#[cfg(test)]
mod tests {
    use std::net::IpAddr;

    use super::virustotal_url;

    fn url(address: &str) -> Option<String> {
        virustotal_url(address.parse::<IpAddr>().unwrap())
    }

    #[test]
    fn returns_canonical_urls_for_ordinary_public_addresses() {
        assert_eq!(
            url("8.8.8.8"),
            Some("https://www.virustotal.com/gui/ip-address/8.8.8.8/detection".into())
        );
        assert_eq!(
            url("2001:4860:0:0:0:0:0:8888"),
            Some("https://www.virustotal.com/gui/ip-address/2001:4860::8888/detection".into())
        );
        assert_eq!(
            url("2606:4700:4700::1111"),
            Some("https://www.virustotal.com/gui/ip-address/2606:4700:4700::1111/detection".into())
        );
    }

    #[test]
    fn rejects_ipv4_special_ranges_at_boundaries() {
        for address in [
            "0.0.0.0",
            "0.255.255.255",
            "10.0.0.0",
            "10.255.255.255",
            "100.64.0.0",
            "100.127.255.255",
            "127.0.0.1",
            "169.254.0.0",
            "169.254.255.255",
            "172.16.0.0",
            "172.31.255.255",
            "192.0.0.0",
            "192.0.0.255",
            "192.0.2.1",
            "192.88.99.1",
            "192.168.0.0",
            "192.168.255.255",
            "198.18.0.0",
            "198.19.255.255",
            "198.51.100.1",
            "203.0.113.1",
            "224.0.0.0",
            "239.255.255.255",
            "240.0.0.0",
            "255.255.255.255",
        ] {
            assert_eq!(url(address), None, "{address} must not be disclosed");
        }

        for address in [
            "1.0.0.0",
            "9.255.255.255",
            "11.0.0.0",
            "100.63.255.255",
            "100.128.0.0",
            "126.255.255.255",
            "128.0.0.0",
            "169.253.255.255",
            "170.0.0.0",
            "172.15.255.255",
            "172.32.0.0",
            "192.87.255.255",
            "192.88.98.255",
            "192.88.100.0",
            "192.167.255.255",
            "192.169.0.0",
            "198.17.255.255",
            "198.20.0.0",
            "198.51.99.255",
            "192.0.1.1",
            "192.0.3.1",
            "198.51.101.0",
            "203.0.112.255",
            "203.0.114.0",
            "223.255.255.255",
        ] {
            assert!(url(address).is_some(), "{address} should be eligible");
        }
    }

    #[test]
    fn rejects_non_native_and_special_ipv6_ranges_at_boundaries() {
        for address in [
            "::",
            "::1",
            "::ffff:8.8.8.8",
            "::ffff:10.0.0.1",
            "1fff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
            "2001::",
            "2001:1ff:ffff:ffff:ffff:ffff:ffff:ffff",
            "2001:db8::",
            "2002::",
            "3ffe::",
            "3fff::",
            "3fff:fff:ffff:ffff:ffff:ffff:ffff:ffff",
            "4000::",
            "fc00::",
            "fe80::",
            "ff00::",
        ] {
            assert_eq!(url(address), None, "{address} must not be disclosed");
        }

        for address in [
            "2000::",
            "2001:200::",
            "2001:db7:ffff:ffff:ffff:ffff:ffff:ffff",
            "2001:db9::",
            "2003::",
            "3ffd:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
            "3fff:1000::",
        ] {
            assert!(url(address).is_some(), "{address} should be eligible");
        }
    }
}
