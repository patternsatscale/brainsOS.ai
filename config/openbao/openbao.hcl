# brainsOS: Segregated OpenBao Secret Manager Configuration (#387)
# Encrypted integrated Raft storage isolated from LiteLLM DB and Authentik Redis.

ui = true
disable_mlock = true

storage "raft" {
  path    = "/openbao/data"
  node_id = "brainsos-openbao-1"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = 1
}
