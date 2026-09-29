require ["vnd.dovecot.pipe", "copy", "envelope", "variables", "fileinto"];

# Inbound reactive mail streaming trigger for brainsOS agent substrate
# When email arrives, pipe envelope recipient as argument to agent-webhook.sh
if envelope :matches "to" "*" {
    set "recipient" "${1}";
    pipe :copy "agent-webhook.sh" ["${recipient}"];
} else {
    pipe :copy "agent-webhook.sh";
}

# Preserve standard mailbox delivery to INBOX
keep;
