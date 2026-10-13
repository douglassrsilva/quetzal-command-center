# Limitações e fronteiras da evidência

- Todos os dados de clientes, rede, tickets, NPS, campanhas e resultados são
  sintéticos e demonstrativos. Eles não provam desempenho em produção.
- A probabilidade de churn vem do modelo individual. PageRank, Personalized
  PageRank, exposição de vizinhos e grupos de relacionamento são sinais
  separados; não são probabilidades de churn nem evidência causal.
- O incidente da jornada é contexto geográfico ou exemplo do mesmo mercado.
  Como `silver_cdrs` não contém tower ID, não há atribuição direta do incidente
  ao cliente selecionado.
- O preflight não executa inferência. AI Gateway é verificado por configuração;
  Managed Memory e AI/BI são verificados por metadados.
- O preflight mostra Genie `READY` porque os três recursos e permissões foram
  resolvidos; isso continua sendo prova de configuração, não de consulta. A
  execução real está separada em `genie-query.json`, recuperada de uma conversa
  histórica concluída. Nenhuma pergunta foi enviada durante esta coleta.
- A prova do Quetzal IQ pertence a uma validação E2E autorizada anterior e
  executou uma inferência. Ela não foi repetida para produzir documentação.
- A campanha E2E provou rejeição de autoaprovação e conflito de versão. A
  aprovação positiva com uma segunda identidade não foi falsificada no remoto;
  esse caminho está coberto por teste de contrato com `ACTION_APPROVER` distinto.
- O total de 1.571.631 triplas é o contrato Delta do snapshot; 1.637.100 é a
  triplestore materializada pelo OntoBricks. A diferença de camadas é esperada
  e está registrada em `graph-ontobricks.json`.
- A validação UI textual cobre a área de campanha persistida em desktop e
  mobile. As capturas existentes são suplementares, não a prova primária.
- O build do frontend produz um chunk JS de aproximadamente 542,51 kB e o Vite
  emite o alerta padrão para chunks acima de 500 kB. Isso não quebra o build,
  mas permanece como oportunidade de code splitting.
- O estado de App, warehouse e serviços é pontual; uma coleta futura pode
  apresentar latência ou disponibilidade diferentes.
- `lakeflow-run.json` prova um refresh histórico concluído em 27/27 fluxos; ele
  não mede qualidade semântica nem frescor futuro das fontes.
- Nenhum job de Lakeflow, geração sintética, ML, Graph Intelligence ou build
  OntoBricks foi reexecutado nesta coleta. Nenhuma campanha foi enviada.
