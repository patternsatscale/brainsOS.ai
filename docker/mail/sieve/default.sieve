require ["vnd.dovecot.pipe", "copy", "envelope", "variables", "fileinto"];

# Inbound reactive push-webhook trigger for autonomous agent fleet
# When email arrives for any *@titan.local fleet address, pipe envelope recipient to agent-webhook.sh
if envelope :matches "to" "*@titan.local" {
    set "recipient" "${1}@titan.local";
    pipe :copy "agent-webhook.sh" ["${recipient}"];
} else {
    pipe :copy "agent-webhook.sh";
}

# Preserve standard mailbox delivery to INBOX
keep;
