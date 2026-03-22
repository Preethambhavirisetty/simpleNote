
from services.storage_service import VectorStore
from services.chunking_service import get_document_objects
from core.settings import init_llama_index_settings
from core.contracts import AccessContext


def ingest(data, reset=False):
    doc_id, llama_docs = get_document_objects(data)
    access_context = AccessContext(
        user_id=data["userid"],
        role=data["role"],
        tenant_id=data.get("tenant_id"),
    )

    with VectorStore() as db:
        db.upsert(
            llama_docs,
            doc_id,
            access_context=access_context,
            reset=reset,
        )
        user_points = db.document_count(access_context=access_context)
        print(f"Data upserted successfully, user points: {user_points}")


def ask(query, userid, role, k=7):
    access_context = AccessContext(user_id=userid, role=role)
    with VectorStore() as db:
        results = db.retrieve_documents(
            query,
            k=k,
            access_context=access_context,
        )

    context = "\n\n".join(doc.text for doc in results)
    print(context)


def simulate_diff_users_ingestion(users):
    for idx, (data_file, data) in enumerate(users):
        with open(data_file, 'r') as f:
            ingest({**data, "text": f.read()})
            print(f"Data has been ingested for user {data['userid']}")

if __name__ == '__main__':
    init_llama_index_settings()



    data1 = {
        "userid": "SAMPLEUSER01",
        "role": "user",
        "tenant_id": "TENANT01",
        "folder_id": "SAMPLESFOLDER01",
        "note_id": "SAMPLENOTE01",
        "folder_title": "SAMPLE FOLDER TITLE1",
        "note_title": "SAMPLE NOTE TITLE1",
        "description": "SAMPLE DESCRIPTION 1",
        "tags": ["tag1", "tag2"]
    }
    data2 = {
        "userid": "SAMPLEUSER02",
        "role": "admin",
        "tenant_id": "TENANT01",
        "folder_id": "SAMPLESFOLDER02",
        "note_id": "SAMPLENOTE02",
        "folder_title": "SAMPLE FOLDER TITLE2",
        "note_title": "SAMPLE NOTE TITLE2",
        "description": "SAMPLE DESCRIPTION 2",
        "tags": ["tag1", "tag2"]
    }



    # simulate_diff_users_ingestion([
    #     ("data1.txt", data1),
    #     ("data2.txt", data2)
    # ])

    # # sample_query = "How to calibrate thremal sensors for deck4?"
    # # sample_query = "there is a code where we need to make a next step"
    # sample_query = "total how many people are working?"
    # print("\nQuestion:", sample_query)
    # answer = ask(sample_query, "SAMPLEUSER02", "user", k=5)

    with VectorStore() as store:
        admin_context = AccessContext(user_id="SYSTEM", role="admin", tenant_id="TENANT01")
        points_count = store.document_count(access_context=admin_context)
        all_docs = store.get_all_document_for_user(admin_context, "SAMPLEUSER02")
        for doc in all_docs:
            print(doc.metadata)
        print(f"Total points (admin): {points_count} / {len(all_docs)}")