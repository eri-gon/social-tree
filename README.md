# social-tree
Help remember names of people I meet in specific social contexts. 

docker run --name keep-crm-postgres \
  -e POSTGRES_USER=eric \
  -e POSTGRES_PASSWORD=password123 \
  -e POSTGRES_DB=keep_social_graph \
  -p 5432:5432 -d postgres